"""Informe de estructura del EPUB, pensado para compartir.

Dos modos:
- General (`bja inspeccionar`): panorama de todo el EPUB.
- Enfocado (`bja inspeccionar --libro qo`): analiza los documentos de un libro, deduce
  qué elementos marcan capítulos y versículos mirando la FORMA de las secuencias
  numéricas, prueba la sugerencia extrayendo el libro y la compara con la configuración
  actual. Con --aplicar, guarda la sugerencia en config.toml.

Por qué funciona la deducción: los números de capítulo de un libro crecen de uno en uno
(1, 2, 3…) y hay tantos como capítulos; los de versículo crecen de uno en uno y vuelven a
empezar en cada capítulo (1…18, 1…26…). Ningún otro número del texto tiene esas formas.
Una marca de capítulo puede llevar texto delante ("Qo 3", "1 Cro 3", "SALMO 23 (22)"):
cuenta el número final, y se comprueba que la regex configurada sepa leerlo.

Los fragmentos de texto se truncan a pocos caracteres: el informe muestra estructura,
no el contenido del libro, y se puede compartir para pedir ayuda.
"""

from __future__ import annotations

import bisect
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path

from bs4.element import NavigableString, Tag

from .config import CAPITULO_REGEX_DEFECTO, Config, ConfigEpub, valor_toml
from .epub import Epub, parsear_xhtml
from .extraccion import (
    InfoDocumento, ResultadoExtraccion, Selectores, documentos_de_libro, es_hoja, extraer, limpiar_documento,
    mapa_documentos, resumen_por_libro, texto_de,
)
from .libros import Libro, obtener
from .texto import LINEA, PARRAFO, Capitulo

_TRUNCAR = 24
_CORTO = 100  # caracteres: umbral de "bloque corto" (línea poética)
_HOJAS = ["p", "div", "li", "blockquote", "dd", "td"]
_ENCABEZADOS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_PRIORIDAD_TAG = {"sup": 0, "span": 1, "b": 2, "strong": 2, "i": 3, "a": 4}
# Abreviatura (o "Capítulo", "Salmo") + número: marca de capítulo con prefijo, en cualquier
# etiqueta. El número cuenta solo si va al final.
_RE_PREFIJADO = re.compile(
    r"^\s*(?:(?:cap[ií]tulo|salmos?)\s+|(?:[1-3]\s*)?[^\W\d_]{1,4}\.?\s+)(\d{1,3})\s*$", re.IGNORECASE
)
_PRESENTACION = {"bloque_corto_chars", "estrofa", "linea_poetica", "rotulo"}


# --------------------------------------------------------------------- utilidades
def _clases(t: Tag) -> list[str]:
    clases = t.get("class") or ""
    if isinstance(clases, list):
        clases = " ".join(clases)
    return sorted(str(clases).split())


def _firma(t: Tag) -> str:
    return t.name + "".join(f".{c}" for c in _clases(t))


def _corto(texto: str, n: int = _TRUNCAR) -> str:
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto if len(texto) <= n else texto[: n - 1] + "…"


def _texto_propio(t: Tag) -> str:
    return " ".join(str(c) for c in t.children if isinstance(c, NavigableString)).strip()


def _tabla(filas: list[list[str]], encabezado: list[str]) -> list[str]:
    anchos = [max(len(str(x)) for x in col) for col in zip(encabezado, *filas)] if filas else [len(h) for h in encabezado]

    def fmt(fila: list[str]) -> str:
        return "  ".join(str(c).rjust(a) if i else str(c).ljust(a) for i, (c, a) in enumerate(zip(fila, anchos)))

    return [fmt(encabezado)] + [fmt(f) for f in filas]


# --------------------------------------------------------------------- CSS
_RE_REGLA = re.compile(r"([^{}]+)\{([^{}]*)\}")
_RE_LONGITUD = re.compile(r"^(-?\d*\.?\d+)(em|rem|px|pt|%)?$")


def _a_em(valor: str) -> float:
    valor = valor.strip().lower().replace("!important", "").strip()
    m = _RE_LONGITUD.match(valor)
    if not m:
        return 0.0
    n = float(m.group(1))
    return {"em": n, "rem": n, "px": n / 16, "pt": n / 12, None: n / 16}.get(m.group(2), 0.0)


def margenes_superiores(hojas: list[str]) -> dict[str, float]:
    """Clase CSS → margen superior en em (solo las que separan visiblemente, ≥ 0.3em).

    Una clase con margen superior marca un bloque con aire encima: en poesía, el comienzo
    de una estrofa. Leerlo de la CSS evita adivinar por el nombre de la clase.
    """
    clases: dict[str, float] = {}
    for css in hojas:
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        for m in _RE_REGLA.finditer(css):
            selectores, cuerpo = m.group(1), m.group(2)
            if "@" in selectores:
                continue
            arriba = 0.0
            for decl in cuerpo.split(";"):
                if ":" not in decl:
                    continue
                prop, val = (x.strip().lower() for x in decl.split(":", 1))
                if prop in ("margin-top", "padding-top"):
                    arriba = max(arriba, _a_em(val))
                elif prop in ("margin", "padding") and val.split():
                    arriba = max(arriba, _a_em(val.split()[0]))
            if arriba < 0.3:
                continue
            for s in selectores.split(","):
                s = s.strip()
                if not s or any(c in s for c in " >+~:[]"):
                    continue
                for cls in re.findall(r"\.([\w-]+)", s):
                    clases[cls] = max(clases.get(cls, 0.0), arriba)
    return clases


# --------------------------------------------------------------------- análisis
@dataclass
class Marca:
    pos: int
    valor: int


@dataclass
class AnalisisDoc:
    href: str
    cuerpo: Tag  # crudo, para los esqueletos
    elementos: list[Tag]
    numericos: dict[str, list[Marca]] = field(default_factory=lambda: defaultdict(list))
    encabezados: dict[str, list[Marca]] = field(default_factory=lambda: defaultdict(list))
    muestras: dict[str, Tag] = field(default_factory=dict)
    bloques: dict[str, list[tuple[int, bool, bool]]] = field(default_factory=lambda: defaultdict(list))
    muestras_bloque: dict[str, Tag] = field(default_factory=dict)
    clases_bloque: Counter = field(default_factory=Counter)
    hojas_crudas: list[tuple[int, int]] = field(default_factory=list)  # (posición, largo) de bloques hoja

    @property
    def marcas_totales(self) -> int:
        return sum(len(v) for v in self.numericos.values())


def analizar_documento(href: str, contenido: bytes, sel: Selectores) -> AnalisisDoc:
    soup = parsear_xhtml(contenido)
    cuerpo = soup.find("body") or soup
    elementos = cuerpo.find_all(True)
    a = AnalisisDoc(href, cuerpo, elementos)
    for pos, t in enumerate(elementos):
        txt = texto_de(t)
        if re.fullmatch(r"\d{1,3}", txt):
            f = _firma(t)
            a.numericos[f].append(Marca(pos, int(txt)))
            a.muestras.setdefault(f, t)
        elif len(txt) < 40:
            m = _RE_PREFIJADO.match(txt)
            n = int(m.group(1)) if m else None
            if n is None and (t.name in _ENCABEZADOS or t.name in ("p", "div")):
                n = sel.numero_capitulo(txt)
            if n is not None:
                f = _firma(t)
                a.encabezados[f].append(Marca(pos, n))
                a.muestras.setdefault(f, t)
        if t.name in _HOJAS and es_hoja(t):
            largo = len(txt)
            if largo:
                a.hojas_crudas.append((pos, largo))
    limpio = parsear_xhtml(contenido)
    cuerpo_limpio = limpio.find("body") or limpio
    limpiar_documento(cuerpo_limpio, sel)
    for blk in cuerpo_limpio.find_all(_HOJAS):
        if not es_hoja(blk):
            continue
        txt = texto_de(blk)
        if not txt:
            continue
        primera = next((s.strip() for s in blk.strings if s.strip()), "")
        empieza = bool(re.fullmatch(r"\d{1,3}[a-z]?", primera))
        termina = bool(re.search(r"[.!?…][\"'»”’)\]]*$", txt))
        f = _firma(blk)
        a.bloques[f].append((len(txt), empieza, termina))
        a.muestras_bloque.setdefault(f, blk)
        a.clases_bloque.update(_clases(blk))
    return a


def _lis(valores: list[int]) -> int:
    """Largo de la subsecuencia estrictamente creciente más larga."""
    colas: list[int] = []
    for v in valores:
        i = bisect.bisect_left(colas, v)
        if i == len(colas):
            colas.append(v)
        else:
            colas[i] = v
    return len(colas)


def puntaje_capitulos(valores: list[int], n: int) -> float:
    """Qué tanto parece una secuencia de números de capítulo de un libro de n capítulos."""
    if n <= 1 or not valores:
        return 0.0
    utiles = [v for v in valores if 1 <= v <= n]
    largo = _lis(utiles)
    ruido = len(valores) - largo
    if ruido > max(3, n // 4):
        return 0.0
    return largo / n


def calidad_versos(valores: list[int]) -> float:
    """Proporción de transiciones que parecen de versículos: +1, repetición o reinicio."""
    if len(valores) < 5:
        return 0.0
    buenas = 0.0
    for a, b in zip(valores, valores[1:]):
        if b == a + 1 or b == a or (b in (1, 2) and a >= b):
            buenas += 1
        elif b == a + 2:
            buenas += 0.5
    return buenas / (len(valores) - 1)


def _colapsar(valores: list[int]) -> list[int]:
    salida: list[int] = []
    for v in valores:
        if not salida or salida[-1] != v:
            salida.append(v)
    return salida


@dataclass
class Candidato:
    firma: str
    valores: list[int]
    puntaje: float


@dataclass
class Sugerencia:
    cambios: dict[str, object] = field(default_factory=dict)
    razones: list[str] = field(default_factory=list)
    capitulo: Candidato | None = None
    capitulo_extra: list[Candidato] = field(default_factory=list)
    versiculo: list[Candidato] = field(default_factory=list)


def _secuencias(analisis: list[AnalisisDoc], fuente: str) -> dict[str, list[Marca]]:
    """Secuencias combinadas en orden de lectura (posiciones desplazadas por documento)."""
    combinadas: dict[str, list[Marca]] = defaultdict(list)
    desplazamiento = 0
    for a in analisis:
        for f, marcas in getattr(a, fuente).items():
            combinadas[f].extend(Marca(m.pos + desplazamiento, m.valor) for m in marcas)
        desplazamiento += len(a.elementos) + 1
    return combinadas


def _huecos(valores: list[int]) -> int:
    """Saltos hacia adelante de más de uno (versículos que faltan en la secuencia)."""
    return sum(1 for a, b in zip(valores, valores[1:]) if b > a + 1)


def _versiculo_principal(numericos: dict[str, list[Marca]], n: int) -> tuple[str, float] | None:
    # Umbral 0.75 y no más: si una parte de los versículos usa otra etiqueta, la principal
    # tiene huecos regulares (1, 2, 4, 5…) y aun así debe reconocerse; los huecos los tapa
    # después la búsqueda de firmas complementarias.
    opciones = []
    for f, marcas in numericos.items():
        valores = [m.valor for m in marcas]
        q = calidad_versos(valores)
        if q >= 0.75 and len(valores) >= max(5, 2 * n):
            opciones.append((len(valores), -_PRIORIDAD_TAG.get(f.split(".")[0], 5), f, q))
    if not opciones:
        return None
    _, _, f, q = max(opciones)
    return f, q


def _versiculos_complementarios(numericos: dict[str, list[Marca]], principal: str) -> list[str]:
    """Otras firmas que RELLENAN huecos de la principal (p. ej. versículos numerados con un
    enlace en vez de un superíndice). Alargar la secuencia no basta: tiene que tapar huecos."""
    actuales = sorted(numericos[principal], key=lambda m: m.pos)
    elegidas = []
    for f, marcas in sorted(numericos.items(), key=lambda kv: -len(kv[1])):
        if f == principal or len(marcas) < 3:
            continue
        base = _colapsar([m.valor for m in actuales])
        mezcla = sorted(actuales + marcas, key=lambda m: m.pos)
        junta = _colapsar([m.valor for m in mezcla])
        tapa = _huecos(base) - _huecos(junta)
        if tapa >= max(2, len(marcas) // 2) and calidad_versos(junta) >= calidad_versos(base) - 0.02:
            elegidas.append(f)
            actuales = mezcla
    return elegidas


def _intercalado(marcas: list[Marca], posiciones_verso: list[int]) -> float:
    """Fracción de marcas de capítulo seguidas de algún versículo antes de la siguiente marca.
    Las de un índice («SALMO 1», «SALMO 2»… seguidos) no tienen versículos entre medio."""
    if not marcas or not posiciones_verso:
        return 1.0
    pos = sorted(m.pos for m in marcas)
    buenas = 0
    for i, p in enumerate(pos):
        fin = pos[i + 1] if i + 1 < len(pos) else float("inf")
        k = bisect.bisect_right(posiciones_verso, p)
        buenas += k < len(posiciones_verso) and posiciones_verso[k] < fin
    return buenas / len(pos)


def _capitulos_complementarios(fuente: dict[str, list[Marca]], principal: str, n: int,
                               excluir: set[str], posiciones_verso: list[int]) -> list[str]:
    """Marcas de capítulo de otra clase que tapan huecos de la principal (en la BJ, «Sal 10»
    dentro del encabezado «SALMO 9-10»). Solo cuentan si casi todos sus números son nuevos
    y la secuencia combinada se parece más a la de los capítulos del libro."""
    actuales = list(fuente[principal])
    elegidas = []
    for f, marcas in sorted(fuente.items(), key=lambda kv: -len(kv[1])):
        if f == principal or f in excluir or _intercalado(marcas, posiciones_verso) < 0.5:
            continue
        valores = {m.valor for m in marcas}
        nuevos = valores - {m.valor for m in actuales}
        if not nuevos or len(nuevos) < 0.8 * len(valores):
            continue
        mezcla = sorted(actuales + marcas, key=lambda m: m.pos)
        if puntaje_capitulos([m.valor for m in mezcla], n) > puntaje_capitulos([m.valor for m in actuales], n):
            elegidas.append(f)
            actuales = mezcla
    return elegidas


def sugerir(analisis: list[AnalisisDoc], libro: Libro, cfg: ConfigEpub, hojas_css: list[str]) -> Sugerencia:
    sel = Selectores.desde(cfg)
    s = Sugerencia()
    muestras: dict[str, Tag] = {}
    for a in analisis:
        for f, t in a.muestras.items():
            muestras.setdefault(f, t)
    n = libro.capitulos

    # 1) versículos: dominan los números del libro, así que la firma principal se deduce
    #    primero, con todos los documentos.
    principal = _versiculo_principal(_secuencias(analisis, "numericos"), n)
    # 2) documentos de TEXTO: los que concentran esos versículos. Las introducciones citan
    #    capítulos en negrita ("véase 3 1-8") y meterían ruido en las secuencias.
    if principal:
        conteo = {a.href: len(a.numericos.get(principal[0], [])) for a in analisis}
        tope = max(conteo.values())
        de_texto = [a for a in analisis if conteo[a.href] >= tope * 0.2]
    else:
        de_texto = analisis
    numericos = _secuencias(de_texto, "numericos")
    if principal:
        firmas = [principal[0], *_versiculos_complementarios(numericos, principal[0])]
        s.versiculo = [Candidato(f, [m.valor for m in numericos[f]], principal[1]) for f in firmas]
        faltan = [f for f in firmas if not (sel.versiculo and sel.versiculo.match(muestras[f]))]
        if faltan:
            s.cambios["versiculo"] = ", ".join(faltan + ([cfg.versiculo] if cfg.versiculo.strip() else []))
        s.razones.append(
            "versículos: " + " + ".join(f"«{c.firma}» ({len(c.valores)})" for c in s.versiculo)
            + " — crecen de uno en uno y vuelven a empezar en cada capítulo"
        )

    # 3) capítulos, también solo en los documentos de texto
    firmas_verso = {c.firma for c in s.versiculo}
    encabezados = _secuencias(de_texto, "encabezados")
    posiciones_verso = sorted(m.pos for f in firmas_verso for m in numericos.get(f, []))
    candidatos = []
    for fuente in (numericos, encabezados):
        for f, marcas in fuente.items():
            if f in firmas_verso:
                continue
            # Una marca de capítulo va seguida de versículos; si no, es un índice o una lista.
            p = puntaje_capitulos([m.valor for m in marcas], n) * _intercalado(marcas, posiciones_verso)
            if p >= (0.5 if n <= 3 else 0.6):
                candidatos.append(Candidato(f, [m.valor for m in marcas], p))
    if candidatos:
        s.capitulo = max(candidatos, key=lambda c: (c.puntaje, -_PRIORIDAD_TAG.get(c.firma.split(".")[0], 5)))
        if s.capitulo.firma in encabezados:
            extra = _capitulos_complementarios(encabezados, s.capitulo.firma, n, firmas_verso, posiciones_verso)
            s.capitulo_extra = [Candidato(f, [m.valor for m in encabezados[f]], 0.0) for f in extra]
        elegidos = [s.capitulo, *s.capitulo_extra]
        faltan = [c.firma for c in elegidos if not (sel.capitulo and sel.capitulo.match(muestras[c.firma]))]
        if faltan:
            s.cambios["capitulo"] = ", ".join(faltan + ([cfg.capitulo] if cfg.capitulo.strip() else []))
        # La regex tiene que saber leer el número de cada marca ("Qo 3" no es solo un número).
        ilegibles = [c.firma for c in elegidos if sel.numero_capitulo(texto_de(muestras[c.firma])) is None]
        if ilegibles and cfg.capitulo_regex != CAPITULO_REGEX_DEFECTO:
            s.cambios["capitulo_regex"] = CAPITULO_REGEX_DEFECTO
        ejemplo = _corto(texto_de(muestras[s.capitulo.firma]), 16)
        razon = (f"capítulos: «{s.capitulo.firma}» (p. ej. «{ejemplo}») aparece {len(s.capitulo.valores)} veces con "
                 f"números que crecen de uno en uno ({_muestra_valores(s.capitulo.valores)}) para un libro de "
                 f"{n} capítulos")
        if s.capitulo_extra:
            razon += "; completan los huecos " + ", ".join(
                f"«{c.firma}» ({_muestra_valores(c.valores)})" for c in s.capitulo_extra)
        if not faltan and "capitulo_regex" not in s.cambios:
            razon += " — tu configuración ya los reconoce"
        s.razones.append(razon)

    # 4) poesía: muchos bloques cortos seguidos = una línea poética por bloque
    total = cortos = 0
    firmas_cortas: Counter[str] = Counter()
    muestras_bloque: dict[str, Tag] = {}
    clases_bloque: Counter[str] = Counter()
    for a in de_texto:
        clases_bloque.update(a.clases_bloque)
        for f, filas in a.bloques.items():
            muestras_bloque.setdefault(f, a.muestras_bloque[f])
            for largo, _emp, _ter in filas:
                total += 1
                if largo <= _CORTO:
                    cortos += 1
                    firmas_cortas[f] += 1
    ya_cubiertas = sel.linea and all(sel.linea.match(muestras_bloque[f]) for f in firmas_cortas)
    poesia = cortos >= 8 and total and cortos / total >= 0.15
    if poesia and cfg.bloque_corto_chars == 0 and not ya_cubiertas:
        s.cambios["bloque_corto_chars"] = _CORTO
        s.razones.append(
            f"poesía: {cortos} de {total} párrafos tienen ≤ {_CORTO} caracteres; cada línea poética es un "
            "párrafo propio, así que los bloques cortos seguidos se leerán como líneas (pausa corta)"
        )

    # 5) estrofas: clases con margen superior en la CSS (se suman a las ya configuradas:
    #    otro libro puede usar otra clase)
    if poesia or cfg.bloque_corto_chars or cfg.linea_poetica:
        margenes = margenes_superiores(hojas_css)
        todos = max(1, total)
        estrofas = sorted(c for c in clases_bloque if c in margenes and clases_bloque[c] <= todos * 0.5)
        actuales = [x.strip() for x in cfg.estrofa.split(",") if x.strip()]
        nuevas = [f".{c}" for c in estrofas if f".{c}" not in actuales]
        if nuevas:
            s.cambios["estrofa"] = ", ".join(actuales + nuevas)
            s.razones.append(
                "estrofas: " + ", ".join(f".{c} (margen {margenes[c]:g}em)" for c in estrofas if f".{c}" in nuevas)
                + " dejan aire encima del párrafo según la CSS del EPUB"
            )
    return s


def _muestra_valores(valores: list[int], n: int = 6) -> str:
    if len(valores) <= n:
        return ", ".join(map(str, valores))
    return ", ".join(map(str, valores[:n])) + f", … {valores[-1]}"


# --------------------------------------------------------------------- informes
@dataclass
class Informe:
    texto: str
    cambios: dict[str, object] = field(default_factory=dict)
    mejora: bool = False


def _puntaje_prueba(res: ResultadoExtraccion, libro: Libro) -> tuple[int, int, int]:
    validos = {c.numero for c in res.capitulos if 1 <= c.numero <= libro.capitulos}
    versos = sum(len(set(c.versiculos)) for c in res.capitulos)
    return (len(validos), versos, -len(res.avisos))


def _resumen_prueba(res: ResultadoExtraccion, libro: Libro) -> str:
    validos = {c.numero for c in res.capitulos if 1 <= c.numero <= libro.capitulos}
    versos = sum(len(set(c.versiculos)) for c in res.capitulos)
    lineas = sum(1 for c in res.capitulos for u in c.unidades if u.ruptura == LINEA)
    parrafos = sum(1 for c in res.capitulos for u in c.unidades if u.ruptura == PARRAFO)
    return (f"{len(validos)}/{libro.capitulos} capítulos · {versos} versículos · {lineas} cortes de línea · "
            f"{parrafos} de párrafo · {len(res.avisos)} avisos · {len(res.descartados)} descartados")


def _vista_previa(cap: Capitulo, max_lineas: int = 26, ancho: int = 46) -> list[str]:
    salida = []
    for linea in cap.a_texto().splitlines()[:max_lineas]:
        salida.append(linea if len(linea) <= ancho else linea[: ancho - 1] + "…")
    return salida


def _esqueleto(a: AnalisisDoc, desde: int, cantidad: int) -> list[str]:
    base = len(list(a.cuerpo.parents))
    salida = []
    for t in a.elementos[max(0, desde) : max(0, desde) + cantidad]:
        nivel = max(0, len(list(t.parents)) - base - 1)
        propio = _corto(_texto_propio(t), 20)
        salida.append(f"{'  ' * nivel}{_firma(t)}{(': ' + propio) if propio else ''}")
    return salida


def _inspeccion_enfocada(epub: Epub, cfg: Config, libro_id: str | None, doc_spec: str | None) -> Informe:
    out: list[str] = []
    mapa = mapa_documentos(epub, cfg.epub)
    libro: Libro | None = obtener(libro_id) if libro_id else None
    if doc_spec is not None:
        docs = [_resolver_doc(mapa, doc_spec)]
    else:
        assert libro is not None
        docs = documentos_de_libro(mapa, libro.id)
        if not docs:
            out.append(f"No encontré documentos de {libro.nombre} por sus títulos.")
            out.append("Títulos que no reconocí (si alguno es el libro, añádelo en [epub.titulos]):")
            for d in mapa:
                for t in d.titulos:
                    if t.modo == "no reconocido":
                        out.append(f"  {d.indice:4}  «{_corto(t.texto, 60)}»")
            return Informe("\n".join(out))

    info = {d.href: d for d in mapa}
    titulo = f"{libro.nombre} ({libro.id}, {libro.capitulos} capítulos)" if libro else docs[0]
    out.append(f"## Documentos de {titulo}")
    for href in docs:
        d = info[href]
        titulos = "; ".join(_corto(t.texto, 40) for t in d.titulos) or "(sin título: continuación)"
        out.append(f"{d.indice:4}  {d.kb:5} KB  {href[:44]:44}  {titulos}")
    out.append("")

    sel = Selectores.desde(cfg.epub)
    elegidos = set(docs)
    contenidos = {doc.href: doc.contenido for doc in epub.documentos() if doc.href in elegidos}
    analisis = [analizar_documento(h, contenidos[h], sel) for h in docs]
    principal = max(analisis, key=lambda a: a.marcas_totales)

    numericos = _secuencias(analisis, "numericos")
    encabezados = _secuencias(analisis, "encabezados")
    filas = []
    for f, marcas in sorted({**numericos, **encabezados}.items(), key=lambda kv: -len(kv[1]))[:12]:
        valores = [m.valor for m in marcas]
        reinicios = sum(1 for x, y in zip(valores, valores[1:]) if y < x)
        parece = []
        if libro and puntaje_capitulos(valores, libro.capitulos) >= 0.6:
            parece.append("capítulos")
        minimo = max(5, 2 * libro.capitulos) if libro else 5
        if calidad_versos(valores) >= 0.85 and len(valores) >= minimo:
            parece.append("versículos")
        filas.append([f, str(len(valores)), str(reinicios), _muestra_valores(valores), " y ".join(parece) or "—"])
    out.append("## Números en el texto (elemento, cuántos, reinicios, valores, parecen)")
    out += _tabla(filas, ["elemento", "n", "reinicios", "valores", "parecen"]) if filas else ["  (ningún elemento contiene solo un número)"]
    out.append("")

    filas = []
    for f, datos in sorted(principal.bloques.items(), key=lambda kv: -len(kv[1]))[:14]:
        n = len(datos)
        medio = sum(d[0] for d in datos) // n
        cortos = sum(1 for d in datos if d[0] <= _CORTO) * 100 // n
        empiezan = sum(1 for d in datos if d[1]) * 100 // n
        terminan = sum(1 for d in datos if d[2]) * 100 // n
        filas.append([f, str(n), str(medio), f"{cortos}%", f"{empiezan}%", f"{terminan}%"])
    out.append(f"## Párrafos en {principal.href} (sin notas)")
    out += _tabla(filas, ["bloque", "n", "largo medio", f"≤{_CORTO} car.", "empiezan con nº", "terminan en punto"])
    out.append("")

    sugerencia: Sugerencia | None = None
    mejora = False
    if libro is not None:
        hojas = epub.hojas_de_estilo()
        margenes = margenes_superiores(hojas)
        presentes = sorted(c for c in principal.clases_bloque if c in margenes)
        if presentes:
            out.append("## Clases con margen superior en la CSS (separan estrofas o párrafos)")
            out.append("  " + ", ".join(f".{c} ({margenes[c]:g}em, {principal.clases_bloque[c]} párrafos)" for c in presentes))
            out.append("")
        sugerencia = sugerir(analisis, libro, cfg.epub, hojas)
        actual = extraer(epub, cfg.epub, libro.id, docs)
        out.append("## Prueba de extracción")
        out.append(f"  Configuración actual: {_resumen_prueba(actual, libro)}")
        mejor = actual
        solo_lectura = False
        if sugerencia.cambios:
            cfg_sug = replace(cfg.epub, **sugerencia.cambios)
            probada = extraer(epub, cfg_sug, libro.id, docs)
            out.append(f"  Con la sugerencia:    {_resumen_prueba(probada, libro)}")
            p_actual, p_probada = _puntaje_prueba(actual, libro), _puntaje_prueba(probada, libro)
            if p_probada > p_actual:
                mejor, mejora = probada, True
            elif p_probada == p_actual:
                # Misma corrección (capítulos, versículos, avisos): solo valen los cambios que
                # mejoran la lectura (pausas de línea y de estrofa); el resto sobra.
                lectura = {k: v for k, v in sugerencia.cambios.items() if k in _PRESENTACION}
                if lectura:
                    if lectura != sugerencia.cambios:
                        probada = extraer(epub, replace(cfg.epub, **lectura), libro.id, docs)
                    sugerencia.cambios = lectura
                    mejor, mejora, solo_lectura = probada, True, True
        out.append("")
        if sugerencia.razones:
            out.append("## Lo que deduje")
            out += [f"  - {r}" for r in sugerencia.razones]
            out.append("")
        actual_sirve = len({c.numero for c in actual.capitulos if 1 <= c.numero <= libro.capitulos}) >= libro.capitulos * 0.9
        if sugerencia.cambios and mejora:
            out.append("## Sugerencia probada (líneas para la sección [epub] de config.toml)")
            if solo_lectura:
                out.append("# Capítulos y versículos ya salen bien; esto mejora las pausas (líneas y estrofas).")
            out += [f"{k} = {valor_toml(v)}" for k, v in sugerencia.cambios.items()]
            out.append("")
        elif sugerencia.cambios and actual_sirve:
            out.append("## La configuración actual ya funciona para este libro; la sugerencia no la mejora.")
            out.append("")
        elif sugerencia.cambios:
            out.append("## La sugerencia no mejora la prueba. Pégame este informe (trabajo/inspeccion.txt).")
            out.append("")

        if mejor.capitulos:
            filas = []
            for c in sorted(mejor.capitulos, key=lambda c: c.numero)[:30]:
                filas.append([str(c.numero), str(len(set(c.versiculos))),
                              str(sum(1 for u in c.unidades if u.ruptura == LINEA)),
                              str(sum(1 for u in c.unidades if u.ruptura == PARRAFO)),
                              str(len(c.secciones)), str(c.caracteres), c.origen.rsplit("/", 1)[-1]])
            out.append("## Capítulos (con la mejor configuración)")
            out += _tabla(filas, ["cap", "vv", "líneas", "párrafos", "secciones", "caracteres", "documento"])
            out.append("")
            primero = min(mejor.capitulos, key=lambda c: c.numero)
            out.append(f"## Vista previa de {libro.id} {primero.numero} (formato canónico, líneas recortadas)")
            out += ["  " + x for x in _vista_previa(primero)]
            out.append("")
        avisos = mejor.avisos + [f"descartado: {d}" for d in mejor.descartados]
        if avisos:
            out.append(f"## Revisar antes de generar el audio ({len(avisos)})")
            out += [f"  - {x}" for x in avisos[:25]]
            out.append("")
        if mejor.notas:
            out.append(f"## Para tu información, no requieren nada ({len(mejor.notas)})")
            out += [f"  · {x}" for x in mejor.notas[:25]]
            out.append("")

    # esqueletos del documento principal
    marcas_verso: list[int] = []
    if sugerencia and sugerencia.versiculo:
        firmas = {c.firma for c in sugerencia.versiculo}
        marcas_verso = sorted(m.pos for f, ms in principal.numericos.items() if f in firmas for m in ms)
    elif principal.numericos:
        f = max(principal.numericos, key=lambda k: len(principal.numericos[k]))
        marcas_verso = [m.pos for m in principal.numericos[f]]
    desde = (marcas_verso[0] - 6) if marcas_verso else 0
    out.append(f"## Esqueleto de {principal.href} desde el primer versículo (texto recortado)")
    out += _esqueleto(principal, desde, 45)
    out.append("")
    if sugerencia and sugerencia.capitulo:
        marcas = principal.numericos.get(sugerencia.capitulo.firma) or principal.encabezados.get(sugerencia.capitulo.firma) or []
        lejanas = [m.pos for m in marcas if m.pos > desde + 45]
        if lejanas:
            out.append(f"## Esqueleto alrededor de una marca de capítulo («{sugerencia.capitulo.firma}»)")
            out += _esqueleto(principal, lejanas[0] - 4, 18)
            out.append("")
    racha = _primera_racha_corta(principal)
    if racha is not None and not (desde <= racha <= desde + 45):
        out.append("## Esqueleto de un pasaje con párrafos cortos (¿poesía?)")
        out += _esqueleto(principal, racha - 2, 30)
        out.append("")

    if libro is not None:
        out.append("## Siguiente paso")
        if sugerencia and sugerencia.cambios and mejora:
            out.append(f"  bja inspeccionar --libro {libro.id} --aplicar   (guarda la sugerencia; deja copia en config.toml.bak)")
            out.append(f"  bja extraer --libro {libro.id}")
        elif actual_sirve:
            out.append(f"  La configuración actual sirve para {libro.nombre}: bja extraer --libro {libro.id}")
        else:
            out.append("  No encontré una configuración clara. Pégame este informe (trabajo/inspeccion.txt).")
    return Informe("\n".join(out), dict(sugerencia.cambios) if (sugerencia and mejora) else {}, mejora)


def _primera_racha_corta(a: AnalisisDoc, largo_racha: int = 3) -> int | None:
    seguidos = 0
    for i, (_pos, largo) in enumerate(a.hojas_crudas):
        if largo <= _CORTO:
            seguidos += 1
            if seguidos >= largo_racha:
                return a.hojas_crudas[i - largo_racha + 1][0]
        else:
            seguidos = 0
    return None


def _resolver_doc(mapa: list[InfoDocumento], spec: str) -> str:
    if spec.isdigit():
        i = int(spec)
        if 0 <= i < len(mapa):
            return mapa[i].href
        raise KeyError(f"No hay documento {i}: el EPUB tiene {len(mapa)} (0–{len(mapa) - 1}).")
    coincidencias = [d.href for d in mapa if spec in d.href]
    if len(coincidencias) == 1:
        return coincidencias[0]
    raise KeyError(f"'{spec}' coincide con {len(coincidencias)} documentos; usa el número de la lista.")


def _inspeccion_general(epub: Epub, cfg: Config, max_esqueleto: int = 90) -> Informe:
    out: list[str] = []
    docs = epub.documentos()
    mapa = mapa_documentos(epub, cfg.epub)
    out.append(f"Documentos en orden de lectura: {len(docs)}")
    out.append("")
    firmas: Counter[str] = Counter()
    vers: Counter[str] = Counter()
    vers_ej: dict[str, list[str]] = defaultdict(list)
    notas: Counter[str] = Counter()
    notas_ej: dict[str, list[str]] = defaultdict(list)
    tipos_epub: Counter[str] = Counter()
    enlaces: Counter[str] = Counter()
    filas_docs: list[str] = []
    for i, doc in enumerate(docs):
        soup = parsear_xhtml(doc.contenido)
        cuerpo = soup.find("body") or soup
        n_vers = 0
        for t in cuerpo.find_all(True):
            firma = _firma(t)
            firmas[firma] += 1
            texto = t.get_text(" ", strip=True)
            if re.fullmatch(r"\d{1,3}[a-z]?", texto):
                vers[firma] += 1
                n_vers += 1
                if len(vers_ej[firma]) < 6:
                    vers_ej[firma].append(texto)
            elif t.name in ("sup", "a", "span") and re.fullmatch(r"[a-z*†‡]{1,3}", texto):
                notas[firma] += 1
                if len(notas_ej[firma]) < 6:
                    notas_ej[firma].append(texto)
            tipo = t.get("epub:type")
            if tipo:
                tipos_epub[f"{firma} [epub:type={tipo}]"] += 1
            href = t.get("href") if t.name == "a" else None
            if href and "#" in str(href):
                destino = str(href).split("#")[0] or "(mismo archivo)"
                enlaces[f"{firma} → {destino}"] += 1
        titulos = mapa[i].titulos
        etiqueta = "; ".join(f"{_corto(t.texto, 30)}→{t.libro or ('notas' if t.modo == 'ignorado' else '?')}" for t in titulos)
        filas_docs.append(f"{i:4}  {len(doc.contenido) // 1024:5} KB  números≈{n_vers:5}  {doc.href[:40]:40}  {etiqueta[:60]}")

    out.append("## Documentos (índice, tamaño, números sueltos, ruta, títulos → libro)")
    out += filas_docs[:300]
    if len(filas_docs) > 300:
        out.append(f"… y {len(filas_docs) - 300} más")
    out.append("")
    out.append("## Etiquetas y clases más frecuentes")
    out += [f"{n:7}  {f}" for f, n in firmas.most_common(60)]
    out.append("")
    out.append("## Elementos cuyo texto es solo un número")
    out += [f"{n:7}  {f}   ej.: {', '.join(vers_ej[f])}" for f, n in vers.most_common(15)] or ["  (ninguno)"]
    out.append("")
    out.append("## Candidatos a LLAMADA DE NOTA (texto = letras o símbolo)")
    out += [f"{n:7}  {f}   ej.: {', '.join(notas_ej[f])}" for f, n in notas.most_common(15)] or ["  (ninguno)"]
    out.append("")
    out.append("## Atributos epub:type")
    out += [f"{n:7}  {f}" for f, n in tipos_epub.most_common(20)] or ["  (ninguno)"]
    out.append("")
    out.append("## Enlaces internos (suelen ser notas o referencias)")
    out += [f"{n:7}  {f}" for f, n in enlaces.most_common(15)] or ["  (ninguno)"]
    out.append("")

    reconocidos = sum(1 for d in mapa for t in d.titulos if t.libro)
    ignorados = sum(1 for d in mapa for t in d.titulos if t.modo == "ignorado")
    dudosos = [(d.indice, t) for d in mapa for t in d.titulos if t.modo in ("no reconocido", "sin ordinal → primer libro")]
    out.append(f"## Títulos: {reconocidos} de libros, {ignorados} de notas (se ignoran), {len(dudosos)} para revisar")
    out += [f"  {i:4}  «{_corto(t.texto, 50)}» → {t.libro or '—'} ({t.modo})" for i, t in dudosos[:40]]
    out.append("")

    candidatos = [d for d in mapa if any(t.libro for t in d.titulos)]
    if candidatos:
        doc_libro = max(candidatos, key=lambda d: d.kb)
        contenido = next(doc.contenido for doc in docs if doc.href == doc_libro.href)
        a = analizar_documento(doc_libro.href, contenido, Selectores.desde(cfg.epub))
        out.append(f"## Esqueleto de '{doc_libro.href}' (el documento de libro más grande; texto recortado)")
        out += _esqueleto(a, 0, max_esqueleto)
        out.append("")

    res = extraer(epub, cfg.epub)
    out.append("## Prueba con la configuración actual de [epub]")
    filas = resumen_por_libro(res)
    out.append(f"Capítulos extraídos: {len(res.capitulos)} · libros: {len(filas)} · avisos: {len(res.avisos)}")
    out += [f"  {i:5} {c}/{e} capítulos" for i, c, e, _v, _ch in filas[:80]]
    out += [f"  - {a}" for a in res.avisos[:15]]
    out.append("")
    out.append("## Siguiente paso")
    out.append("  Analiza un libro concreto y obtén selectores probados:  bja inspeccionar --libro qo")
    return Informe("\n".join(out))


def inspeccionar(cfg: Config, ruta_epub: Path | None = None, libro: str | None = None,
                 doc: str | None = None) -> Informe:
    ruta = ruta_epub or cfg.ruta_epub()
    with Epub(ruta) as epub:
        cabecera = [f"EPUB: {Path(ruta).name}",
                    f"DRM: {'PROTEGIDO — ' if epub.drm.protegido else ''}{epub.drm.motivo}"]
        if epub.drm.protegido:
            cabecera += ["", "El pipeline no procesa EPUB con DRM ni intenta desprotegerlos."]
            return Informe("\n".join(cabecera) + "\n")
        if libro or doc is not None:
            inf = _inspeccion_enfocada(epub, cfg, libro, doc)
        else:
            inf = _inspeccion_general(epub, cfg)
    inf.texto = "\n".join(cabecera) + "\n\n" + inf.texto + "\n"
    return inf
