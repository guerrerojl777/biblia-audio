"""Plan de trozos: convierte un capítulo canónico en peticiones de síntesis.

Decisiones de diseño (el "por qué" de cada regla):
- Se corta SIEMPRE en párrafo y sección: así la pausa larga es nuestra y medible,
  no una adivinanza del motor.
- Dentro de un párrafo se agrupan versículos hasta ~objetivo_chars y se corta en fin
  de oración. Cortar en fin de VERSÍCULO no sirve: muchas oraciones cruzan versículos
  y el motor les pondría entonación final a medias.
- Nunca se supera max_chars (Deepgram acepta 2000 por petición). Si hay que cortar
  antes, se busca el último fin de oración disponible.
- Las líneas poéticas van dentro del mismo trozo separadas por salto de línea; si una
  línea no termina en puntuación se le añade una coma para inducir la pausa. La coma
  no cambia las palabras, así que la verificación no la ve.
- Se registra en qué token empieza cada versículo: con eso, la transcripción de
  verificación da la marca de tiempo de cada versículo sin trabajo extra.
- Las cantidades en cifras se escriben en palabras antes de pedir el audio: cada motor
  lee "46.500" a su manera (o como decimal); en palabras no hay ambigüedad.
- Las palabras en mayúsculas ("LA AMADA") pasan a minúsculas con inicial: un motor puede
  deletrear lo que parece una sigla.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .config import Config
from .lexico import Lexico
from .libros import Libro
from .normalizar import numeros_a_palabras, tokenizar
from .texto import LINEA, NINGUNA, PARRAFO, SECCION, VERSICULO, Capitulo, Unidad

_FIN_ORACION = re.compile(r"[.!?…][\"'»”’)\]]*$")
_FIN_DEBIL = re.compile(r"[;:][\"'»”’)\]]*$")
_TERMINA_EN_PUNTUACION = re.compile(r"[.,;:!?…»”’)\]—–-]$")
_PALABRA_MAYUS = r"[A-ZÁÉÍÓÚÑÜ]{2,}"
_RE_RACHA_MAYUS = re.compile(rf"\b{_PALABRA_MAYUS}(?:\s+{_PALABRA_MAYUS})*\b")
_RE_ROMANO = re.compile(r"M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})")
_NO_ROMANOS = {"MI", "DI", "VI", "LI", "CI", "MIL", "DIC"}  # palabras que también son numerales


def _es_romano(palabra: str) -> bool:
    return bool(_RE_ROMANO.fullmatch(palabra)) and palabra not in _NO_ROMANOS


def suavizar_mayusculas(texto: str) -> str:
    """'LA AMADA.' → 'La Amada.'; 'SEÑOR' → 'Señor'. Una palabra suelta en mayúsculas solo
    cambia si tiene 4 letras o más (o tilde): 'Antíoco IV' y una sigla corta quedan como están."""
    def suavizar(m: re.Match[str]) -> str:
        palabras = m.group().split()
        if len(palabras) == 1:
            p = palabras[0]
            if _es_romano(p) or (len(p) < 4 and not re.search(r"[ÁÉÍÓÚ]", p)):
                return p
        return re.sub(_PALABRA_MAYUS, lambda x: x.group() if _es_romano(x.group()) else x.group().capitalize(), m.group())

    return _RE_RACHA_MAYUS.sub(suavizar, texto)


@dataclass
class Trozo:
    indice: int
    texto: str
    versos: list[tuple[str, int]]  # (versículo, índice del token donde empieza)
    pausa_ms: int  # silencio que se inserta DESPUÉS de este trozo
    anuncio: bool = False
    secciones: list[str] = field(default_factory=list)  # títulos que preceden a este trozo

    @property
    def caracteres(self) -> int:
        return len(self.texto)

    def a_dict(self) -> dict:
        d = asdict(self)
        d["versos"] = [list(v) for v in self.versos]
        return d


def _pausa(cfg: Config, ruptura: int) -> int:
    p = cfg.pausas
    return {
        NINGUNA: p.versiculo,
        LINEA: p.linea,
        VERSICULO: p.versiculo,
        PARRAFO: p.parrafo,
        SECCION: p.seccion,
    }[ruptura]


def limpiar_texto(texto: str, quitar: str = "") -> str:
    if quitar:
        texto = texto.translate({ord(c): None for c in quitar})
    texto = re.sub(r"\s+", " ", texto).strip()
    texto = re.sub(r"\s+([,.;:!?…»”’)\]])", r"\1", texto)
    texto = re.sub(r"([«“‘(\[¿¡])\s+", r"\1", texto)
    return texto


def _partir_texto(texto: str, max_chars: int) -> list[str]:
    """Parte un texto demasiado largo: oraciones, luego ; : , y en último caso espacios."""
    for patron in (r"(?<=[.!?…»”])\s+", r"(?<=[;:])\s+", r"(?<=,)\s+", r"\s+"):
        partes = [p for p in re.split(patron, texto) if p]
        if all(len(p) <= max_chars for p in partes) or patron == r"\s+":
            break
    piezas: list[str] = []
    for parte in partes:
        if piezas and len(piezas[-1]) + 1 + len(parte) <= max_chars:
            piezas[-1] = f"{piezas[-1]} {parte}"
        else:
            piezas.append(parte)
    return piezas


def _partir_unidad(u: Unidad, max_chars: int) -> list[Unidad]:
    if len(u.texto) <= max_chars:
        return [u]
    piezas = _partir_texto(u.texto, max_chars)
    return [
        Unidad(u.versiculo, p, u.ruptura if i == 0 else NINGUNA, u.inicia_versiculo and i == 0)
        for i, p in enumerate(piezas)
    ]


def _unir(grupo: list[Unidad], poesia_coma: bool) -> tuple[str, list[tuple[str, int]]]:
    textos: list[str] = []
    separadores: list[str] = []
    versos: list[tuple[str, int]] = []
    tokens = 0
    for i, u in enumerate(grupo):
        if i > 0:
            if u.ruptura == LINEA:
                if poesia_coma and not _TERMINA_EN_PUNTUACION.search(textos[-1]):
                    textos[-1] += ","
                separadores.append("\n")
            else:
                separadores.append(" ")
        if u.inicia_versiculo:
            versos.append((u.versiculo, tokens))
        tokens += len(tokenizar(u.texto))
        textos.append(u.texto)
    texto = textos[0] + "".join(s + t for s, t in zip(separadores, textos[1:]))
    return texto, versos


def _mejor_corte(grupo: list[Unidad]) -> int | None:
    """Índice de la última unidad tras la cual conviene cortar (fin de oración > ; o :)."""
    for patron in (_FIN_ORACION, _FIN_DEBIL):
        for k in range(len(grupo) - 1, -1, -1):
            if patron.search(grupo[k].texto):
                return k
    return None


def planificar(cap: Capitulo, libro: Libro, cfg: Config, lexico: Lexico, max_chars_proveedor: int) -> list[Trozo]:
    max_chars = min(cfg.plan.max_chars, max_chars_proveedor)
    objetivo = min(cfg.plan.objetivo_chars, max_chars)
    poesia_coma = cfg.plan.poesia_coma

    titulos_por_unidad: dict[int, list[str]] = {}
    for s in cap.secciones:
        titulos_por_unidad.setdefault(s.antes_de, []).append(s.titulo)

    items: list[tuple[Unidad, list[str]]] = []
    for i, u in enumerate(cap.unidades):
        # Mayúsculas antes del léxico (así "QOHÉLET" también encuentra su entrada) y cifras al
        # final (el léxico no las ve).
        texto = suavizar_mayusculas(limpiar_texto(u.texto, cfg.plan.quitar_caracteres))
        texto = numeros_a_palabras(lexico.reescribir_comun(texto))
        if not texto:
            continue
        limpia = Unidad(u.versiculo, texto, u.ruptura, u.inicia_versiculo)
        for j, pieza in enumerate(_partir_unidad(limpia, max_chars)):
            items.append((pieza, titulos_por_unidad.get(i, []) if j == 0 else []))

    trozos: list[Trozo] = []
    if cfg.plan.anunciar_capitulo:
        trozos.append(Trozo(0, libro.anuncio(cap.numero), [], cfg.pausas.anuncio, anuncio=True))

    grupo: list[Unidad] = []
    titulos: list[str] = []

    def largo(g: list[Unidad]) -> int:
        return len(_unir(g, poesia_coma)[0]) if g else 0

    def cerrar(g: list[Unidad], pausa: int, tits: list[str]) -> None:
        texto, versos = _unir(g, poesia_coma)
        trozos.append(Trozo(len(trozos), texto, versos, pausa, False, list(tits)))

    for u, tits in items:
        if grupo:
            if u.ruptura >= PARRAFO:
                cerrar(grupo, _pausa(cfg, u.ruptura), titulos)
                grupo, titulos = [], []
            elif largo(grupo + [u]) > max_chars:
                k = _mejor_corte(grupo)
                if k is not None and k < len(grupo) - 1:
                    cerrar(grupo[: k + 1], _pausa(cfg, grupo[k + 1].ruptura), titulos)
                    grupo, titulos = grupo[k + 1 :], []
                    if largo(grupo + [u]) > max_chars:
                        cerrar(grupo, _pausa(cfg, u.ruptura), [])
                        grupo = []
                else:
                    cerrar(grupo, _pausa(cfg, u.ruptura), titulos)
                    grupo, titulos = [], []
            elif largo(grupo) >= objetivo and _FIN_ORACION.search(grupo[-1].texto):
                cerrar(grupo, _pausa(cfg, u.ruptura), titulos)
                grupo, titulos = [], []
        titulos.extend(tits)
        grupo.append(u)

    if grupo:
        cerrar(grupo, cfg.pausas.final, titulos)
    elif trozos:
        trozos[-1].pausa_ms = cfg.pausas.final
    return trozos
