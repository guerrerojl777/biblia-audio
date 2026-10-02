"""Formato canónico de un capítulo: un .txt legible, editable a mano y fácil de comparar con diff.

Es la frontera entre "conseguir el texto" (EPUB, copia manual…) y "producir audio".
Todo lo que viene después solo lee este formato.

    # gn 1                 cabecera obligatoria: id del libro y número de capítulo
    ## Título de sección   título editorial: NO se lee; queda en el índice
    (línea vacía)          separa párrafos → pausa larga
    12 Texto…              empieza el versículo 12 (también 12a, 40ab, o 24-25 si la edición los une)
    / Texto…               nueva línea poética dentro del versículo actual → pausa corta
    + Texto…               continuación del versículo actual tras un salto de párrafo
    % comentario           se ignora (útil para notas tuyas; la extracción anota así los
                           versículos que el EPUB trae entre corchetes, sin texto)

Una línea sin prefijo reconocido que no empieza con número se trata como continuación.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .errores import TextoInvalido

# Fuerza de la frontera ANTES de una unidad de texto (decide la pausa si ahí se corta).
NINGUNA, LINEA, VERSICULO, PARRAFO, SECCION = 0, 1, 2, 3, 4

ETIQUETA_VERSO = r"\d{1,3}[a-z]{0,2}(?:-\d{1,3}[a-z]{0,2})?"
_RE_CABECERA = re.compile(r"^#\s+(\S+)\s+(\d{1,3})\s*$")
_RE_SECCION = re.compile(r"^##\s+(.*\S)\s*$")
_RE_VERSICULO = re.compile(rf"^({ETIQUETA_VERSO})\s+(.*\S)\s*$")
_RE_SOLO_ETIQUETA = re.compile(rf"{ETIQUETA_VERSO}")
_RE_POETICA = re.compile(r"^/\s+(.*\S)\s*$")
_RE_CONTINUACION = re.compile(r"^\+\s+(.*\S)\s*$")


@dataclass
class Unidad:
    """Un tramo de texto continuo: un versículo, una línea poética o una continuación."""

    versiculo: str
    texto: str
    ruptura: int
    inicia_versiculo: bool
    implicita: bool = False  # extracción: texto sin número que se asumió como versículo (1 o 0)


@dataclass
class Seccion:
    titulo: str
    antes_de: int  # índice de la unidad que la sigue


@dataclass
class Omitido:
    """Versículo que la edición numera entre corchetes y no trae en el texto ("[21]")."""

    versiculo: str
    antes_de: int  # índice de la unidad que lo sigue


@dataclass
class Capitulo:
    libro: str
    numero: int
    unidades: list[Unidad] = field(default_factory=list)
    secciones: list[Seccion] = field(default_factory=list)
    omitidos: list[Omitido] = field(default_factory=list)  # se escriben como comentario %
    # Metadatos de extracción (no se escriben en el .txt):
    origen: str = ""  # documento del EPUB donde empezó
    explicito: bool = True  # False si se asumió el capítulo 1 sin marca
    avisos: list[str] = field(default_factory=list)  # solo se informan si el capítulo se conserva
    fragmentos: list[list[str]] = field(default_factory=list)  # versículos de cada trozo unido (traspuestos)
    numerados: int = 0  # versículos con número explícito y texto (los asumidos no cuentan)

    @property
    def versiculos(self) -> list[str]:
        vistos: list[str] = []
        for u in self.unidades:
            if u.inicia_versiculo:
                vistos.append(u.versiculo)
        return vistos

    @property
    def caracteres(self) -> int:
        return sum(len(u.texto) for u in self.unidades)

    def a_texto(self) -> str:
        lineas = [f"# {self.libro} {self.numero}"]
        titulos: dict[int, list[str]] = {}
        for s in self.secciones:
            titulos.setdefault(s.antes_de, []).append(s.titulo)
        omitidos: dict[int, list[str]] = {}
        for o in self.omitidos:
            omitidos.setdefault(o.antes_de, []).append(o.versiculo)
        for i, u in enumerate(self.unidades):
            for t in titulos.get(i, []):
                if lineas[-1] != "":
                    lineas.append("")
                lineas.append(f"## {t}")
            for v in omitidos.get(i, []):
                lineas.append(f"% [{v}] el EPUB trae este número entre corchetes, sin texto: no se lee")
            if u.ruptura >= PARRAFO and i > 0 and lineas[-1] != "" and not lineas[-1].startswith("## "):
                lineas.append("")
            if u.inicia_versiculo:
                lineas.append(f"{u.versiculo} {u.texto}")
            elif u.ruptura == LINEA:
                lineas.append(f"/ {u.texto}")
            else:
                lineas.append(f"+ {u.texto}")
        for v in omitidos.get(len(self.unidades), []):
            lineas.append(f"% [{v}] el EPUB trae este número entre corchetes, sin texto: no se lee")
        for t in titulos.get(len(self.unidades), []):
            lineas += ["", f"## {t}"]
        return "\n".join(lineas) + "\n"


def parsear(texto: str, origen: str = "<texto>") -> Capitulo:
    cap: Capitulo | None = None
    pendiente = NINGUNA
    actual: str | None = None
    for n, cruda in enumerate(texto.splitlines(), start=1):
        linea = cruda.strip()
        if linea.startswith("%"):
            continue
        if cap is None:
            if not linea:
                continue
            m = _RE_CABECERA.match(linea)
            if not m:
                raise TextoInvalido(f"{origen}:{n}: la primera línea debe ser '# <libro> <capítulo>', p. ej. '# gn 1'.")
            cap = Capitulo(libro=m.group(1).lower(), numero=int(m.group(2)))
            continue
        if not linea:
            if cap.unidades:
                pendiente = max(pendiente, PARRAFO)
            continue
        if m := _RE_SECCION.match(linea):
            cap.secciones.append(Seccion(m.group(1), len(cap.unidades)))
            pendiente = max(pendiente, SECCION)
            continue
        if linea.startswith("# "):
            raise TextoInvalido(f"{origen}:{n}: solo puede haber una cabecera '#' por archivo.")
        if _RE_SOLO_ETIQUETA.fullmatch(linea):
            raise TextoInvalido(f"{origen}:{n}: el versículo {linea} no tiene texto (bórralo o complétalo).")
        if m := _RE_VERSICULO.match(linea):
            actual = m.group(1)
            cap.unidades.append(Unidad(actual, _limpiar(m.group(2)), max(pendiente, VERSICULO), True))
            pendiente = NINGUNA
            continue
        if actual is None:
            raise TextoInvalido(f"{origen}:{n}: hay texto antes del primer número de versículo.")
        if m := _RE_POETICA.match(linea):
            cap.unidades.append(Unidad(actual, _limpiar(m.group(1)), max(pendiente, LINEA), False))
        else:
            m = _RE_CONTINUACION.match(linea)
            cuerpo = m.group(1) if m else linea
            cap.unidades.append(Unidad(actual, _limpiar(cuerpo), pendiente, False))
        pendiente = NINGUNA
    if cap is None:
        raise TextoInvalido(f"{origen}: archivo vacío (falta la cabecera '# <libro> <capítulo>').")
    if not cap.unidades:
        raise TextoInvalido(f"{origen}: el capítulo no tiene versículos.")
    return cap


def _limpiar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def leer(ruta: Path) -> Capitulo:
    return parsear(Path(ruta).read_text(encoding="utf-8"), origen=str(ruta))


def escribir_atomico(ruta: Path, contenido: str | bytes) -> None:
    """Escribe a un temporal y lo renombra: nunca deja un archivo a medias."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    modo = "wb" if isinstance(contenido, bytes) else "w"
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=f".{ruta.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, modo, **({} if modo == "wb" else {"encoding": "utf-8", "newline": "\n"})) as f:
            f.write(contenido)
        os.replace(tmp, ruta)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def escribir(cap: Capitulo, ruta: Path) -> None:
    escribir_atomico(ruta, cap.a_texto())


def ruta_capitulo(dir_texto: Path, libro: str, capitulo: int) -> Path:
    return Path(dir_texto) / libro / f"{capitulo:03d}.txt"
