"""Catálogo de los 73 libros del canon católico, en el orden de la Biblia de Jerusalén.

Cada libro tiene:
- id: identificador corto en ASCII, usado en archivos y en la CLI (gn, 1s, sal, mt…).
- nombre: para etiquetas ID3 y tablas.
- hablado: cómo se anuncia en voz al inicio de cada capítulo.
- capitulos: conteo informativo (numeración hebrea, la que usa la BJ). Solo se usa
  para mostrar progreso y avisar de rarezas; nunca bloquea nada.
- bases/abrev/alias: para reconocer el título del libro dentro del EPUB.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Libro:
    id: str
    nombre: str
    hablado: str
    capitulos: int
    testamento: str  # "AT" o "NT"
    orden: int
    numero: int | None = None  # 1, 2 o 3 en libros numerados (1 Samuel…); None en el resto
    bases: tuple[str, ...] = ()  # nombres sin ordinal, para reconocer títulos
    abrev: tuple[str, ...] = ()  # solo coincidencia exacta
    alias: tuple[str, ...] = ()  # coincidencia exacta

    def anuncio(self, capitulo: int) -> str:
        """Frase que se lee al inicio de un capítulo: 'Génesis. Capítulo uno.'"""
        from num2words import num2words

        n = num2words(capitulo, lang="es")
        if capitulo == 0:  # texto antes del capítulo 1 (prólogo del Eclesiástico)
            return f"{self.hablado}. Prólogo."
        if self.id == "sal":
            return f"Salmo {n}."
        if self.capitulos == 1:
            return f"{self.hablado}."
        return f"{self.hablado}. Capítulo {n}."


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes, sin puntuación, espacios simples. Para comparar títulos."""
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s]", " ", t).replace("_", " ")
    return re.sub(r"\s+", " ", t).strip()


_ORDINALES = {
    1: ("1", "i", "primer", "primero", "primera"),
    2: ("2", "ii", "segundo", "segunda"),
    3: ("3", "iii", "tercer", "tercero", "tercera"),
}
_PREFIJOS = {
    1: ("1", "i", "primero de", "primera de", "primer libro de", "primera carta de",
        "primera carta a", "primera epistola de", "primera epistola a"),
    2: ("2", "ii", "segundo de", "segunda de", "segundo libro de", "segunda carta de",
        "segunda carta a", "segunda epistola de", "segunda epistola a"),
    3: ("3", "iii", "tercera de", "tercera carta de", "tercera epistola de"),
}


def _l(orden, id, nombre, hablado, caps, test, *, numero=None, bases=(), abrev=(), alias=()):
    return Libro(id, nombre, hablado, caps, test, orden, numero, tuple(bases), tuple(abrev), tuple(alias))


LIBROS: tuple[Libro, ...] = (
    _l(1, "gn", "Génesis", "Génesis", 50, "AT", bases=("genesis",), abrev=("gn", "gen"), alias=("libro del genesis",)),
    _l(2, "ex", "Éxodo", "Éxodo", 40, "AT", bases=("exodo",), abrev=("ex", "exo"), alias=("libro del exodo",)),
    _l(3, "lv", "Levítico", "Levítico", 27, "AT", bases=("levitico",), abrev=("lv", "lev")),
    _l(4, "nm", "Números", "Números", 36, "AT", bases=("numeros",), abrev=("nm", "num")),
    _l(5, "dt", "Deuteronomio", "Deuteronomio", 34, "AT", bases=("deuteronomio",), abrev=("dt", "deut")),
    _l(6, "jos", "Josué", "Josué", 24, "AT", bases=("josue",), abrev=("jos",)),
    _l(7, "jc", "Jueces", "Jueces", 21, "AT", bases=("jueces",), abrev=("jc", "jue")),
    _l(8, "rt", "Rut", "Rut", 4, "AT", bases=("rut", "ruth"), abrev=("rt",)),
    _l(9, "1s", "1 Samuel", "Primer libro de Samuel", 31, "AT", numero=1, bases=("samuel",), abrev=("1s", "1 s", "1 sam", "1sam")),
    _l(10, "2s", "2 Samuel", "Segundo libro de Samuel", 24, "AT", numero=2, bases=("samuel",), abrev=("2s", "2 s", "2 sam", "2sam")),
    _l(11, "1r", "1 Reyes", "Primer libro de los Reyes", 22, "AT", numero=1, bases=("reyes", "los reyes"), abrev=("1r", "1 r", "1 re", "1 rey")),
    _l(12, "2r", "2 Reyes", "Segundo libro de los Reyes", 25, "AT", numero=2, bases=("reyes", "los reyes"), abrev=("2r", "2 r", "2 re", "2 rey")),
    _l(13, "1cro", "1 Crónicas", "Primer libro de las Crónicas", 29, "AT", numero=1, bases=("cronicas", "las cronicas", "paralipomenos"), abrev=("1cro", "1 cro", "1 cr", "1 cron")),
    _l(14, "2cro", "2 Crónicas", "Segundo libro de las Crónicas", 36, "AT", numero=2, bases=("cronicas", "las cronicas", "paralipomenos"), abrev=("2cro", "2 cro", "2 cr", "2 cron")),
    _l(15, "esd", "Esdras", "Esdras", 10, "AT", bases=("esdras",), abrev=("esd",)),
    _l(16, "ne", "Nehemías", "Nehemías", 13, "AT", bases=("nehemias",), abrev=("ne", "neh")),
    _l(17, "tb", "Tobías", "Tobías", 14, "AT", bases=("tobias", "tobit"), abrev=("tb", "tob")),
    _l(18, "jdt", "Judit", "Judit", 16, "AT", bases=("judit",), abrev=("jdt",)),
    _l(19, "est", "Ester", "Ester", 10, "AT", bases=("ester", "esther"), abrev=("est",)),
    _l(20, "1m", "1 Macabeos", "Primer libro de los Macabeos", 16, "AT", numero=1, bases=("macabeos", "los macabeos"), abrev=("1m", "1 m", "1 mac")),
    _l(21, "2m", "2 Macabeos", "Segundo libro de los Macabeos", 15, "AT", numero=2, bases=("macabeos", "los macabeos"), abrev=("2m", "2 m", "2 mac")),
    _l(22, "jb", "Job", "Job", 42, "AT", bases=("job",), abrev=("jb",)),
    _l(23, "sal", "Salmos", "Salmos", 150, "AT", bases=("salmos",), abrev=("sal", "sl", "ps"), alias=("libro de los salmos", "salterio")),
    _l(24, "pr", "Proverbios", "Proverbios", 31, "AT", bases=("proverbios",), abrev=("pr", "prov")),
    _l(25, "qo", "Eclesiastés", "Eclesiastés", 12, "AT", bases=("eclesiastes", "qohelet", "cohelet"), abrev=("qo", "ecl")),
    _l(26, "ct", "Cantar de los Cantares", "Cantar de los Cantares", 8, "AT", bases=("cantar de los cantares", "cantico de los canticos"), abrev=("ct", "cant"), alias=("cantar",)),
    _l(27, "sb", "Sabiduría", "Sabiduría", 19, "AT", bases=("sabiduria",), abrev=("sb", "sab")),
    _l(28, "si", "Eclesiástico", "Eclesiástico", 51, "AT", bases=("eclesiastico", "siracida", "sirac", "ben sira"), abrev=("si", "eclo")),
    _l(29, "is", "Isaías", "Isaías", 66, "AT", bases=("isaias",), abrev=("is",)),
    _l(30, "jr", "Jeremías", "Jeremías", 52, "AT", bases=("jeremias",), abrev=("jr", "jer")),
    _l(31, "lm", "Lamentaciones", "Lamentaciones", 5, "AT", bases=("lamentaciones",), abrev=("lm", "lam")),
    _l(32, "ba", "Baruc", "Baruc", 6, "AT", bases=("baruc", "baruch"), abrev=("ba", "bar")),
    _l(33, "ez", "Ezequiel", "Ezequiel", 48, "AT", bases=("ezequiel",), abrev=("ez",)),
    _l(34, "dn", "Daniel", "Daniel", 14, "AT", bases=("daniel",), abrev=("dn", "dan")),
    _l(35, "os", "Oseas", "Oseas", 14, "AT", bases=("oseas",), abrev=("os",)),
    _l(36, "jl", "Joel", "Joel", 4, "AT", bases=("joel",), abrev=("jl",)),
    _l(37, "am", "Amós", "Amós", 9, "AT", bases=("amos",), abrev=("am",)),
    _l(38, "abd", "Abdías", "Abdías", 1, "AT", bases=("abdias",), abrev=("abd",)),
    _l(39, "jon", "Jonás", "Jonás", 4, "AT", bases=("jonas",), abrev=("jon",)),
    _l(40, "mi", "Miqueas", "Miqueas", 7, "AT", bases=("miqueas",), abrev=("mi", "miq")),
    _l(41, "na", "Nahúm", "Nahúm", 3, "AT", bases=("nahum", "nahun"), abrev=("na",)),
    _l(42, "ha", "Habacuc", "Habacuc", 3, "AT", bases=("habacuc",), abrev=("ha", "hab")),
    _l(43, "so", "Sofonías", "Sofonías", 3, "AT", bases=("sofonias",), abrev=("so", "sof")),
    _l(44, "ag", "Ageo", "Ageo", 2, "AT", bases=("ageo",), abrev=("ag",)),
    _l(45, "za", "Zacarías", "Zacarías", 14, "AT", bases=("zacarias",), abrev=("za", "zac")),
    _l(46, "ml", "Malaquías", "Malaquías", 3, "AT", bases=("malaquias",), abrev=("ml", "mal")),
    _l(47, "mt", "Mateo", "Evangelio según san Mateo", 28, "NT", bases=("mateo",), abrev=("mt",)),
    _l(48, "mc", "Marcos", "Evangelio según san Marcos", 16, "NT", bases=("marcos",), abrev=("mc",)),
    _l(49, "lc", "Lucas", "Evangelio según san Lucas", 24, "NT", bases=("lucas",), abrev=("lc",)),
    _l(50, "jn", "Juan", "Evangelio según san Juan", 21, "NT", bases=("juan",), abrev=("jn",)),
    _l(51, "hch", "Hechos", "Hechos de los Apóstoles", 28, "NT", bases=("hechos de los apostoles", "hechos"), abrev=("hch",)),
    _l(52, "rm", "Romanos", "Carta a los Romanos", 16, "NT", bases=("romanos",), abrev=("rm", "rom")),
    _l(53, "1co", "1 Corintios", "Primera carta a los Corintios", 16, "NT", numero=1, bases=("corintios", "los corintios"), abrev=("1co", "1 co", "1 cor")),
    _l(54, "2co", "2 Corintios", "Segunda carta a los Corintios", 13, "NT", numero=2, bases=("corintios", "los corintios"), abrev=("2co", "2 co", "2 cor")),
    _l(55, "ga", "Gálatas", "Carta a los Gálatas", 6, "NT", bases=("galatas",), abrev=("ga", "gal")),
    _l(56, "ef", "Efesios", "Carta a los Efesios", 6, "NT", bases=("efesios",), abrev=("ef",)),
    _l(57, "flp", "Filipenses", "Carta a los Filipenses", 4, "NT", bases=("filipenses",), abrev=("flp", "fil")),
    _l(58, "col", "Colosenses", "Carta a los Colosenses", 4, "NT", bases=("colosenses",), abrev=("col",)),
    _l(59, "1ts", "1 Tesalonicenses", "Primera carta a los Tesalonicenses", 5, "NT", numero=1, bases=("tesalonicenses", "los tesalonicenses"), abrev=("1ts", "1 ts", "1 tes")),
    _l(60, "2ts", "2 Tesalonicenses", "Segunda carta a los Tesalonicenses", 3, "NT", numero=2, bases=("tesalonicenses", "los tesalonicenses"), abrev=("2ts", "2 ts", "2 tes")),
    _l(61, "1tm", "1 Timoteo", "Primera carta a Timoteo", 6, "NT", numero=1, bases=("timoteo",), abrev=("1tm", "1 tm", "1 tim")),
    _l(62, "2tm", "2 Timoteo", "Segunda carta a Timoteo", 4, "NT", numero=2, bases=("timoteo",), abrev=("2tm", "2 tm", "2 tim")),
    _l(63, "tt", "Tito", "Carta a Tito", 3, "NT", bases=("tito",), abrev=("tt", "tit")),
    _l(64, "flm", "Filemón", "Carta a Filemón", 1, "NT", bases=("filemon",), abrev=("flm",)),
    _l(65, "hb", "Hebreos", "Carta a los Hebreos", 13, "NT", bases=("hebreos",), abrev=("hb", "heb")),
    _l(66, "st", "Santiago", "Carta de Santiago", 5, "NT", bases=("santiago",), abrev=("st", "sant")),
    _l(67, "1p", "1 Pedro", "Primera carta de san Pedro", 5, "NT", numero=1, bases=("pedro", "san pedro"), abrev=("1p", "1 p", "1 pe", "1 ped")),
    _l(68, "2p", "2 Pedro", "Segunda carta de san Pedro", 3, "NT", numero=2, bases=("pedro", "san pedro"), abrev=("2p", "2 p", "2 pe", "2 ped")),
    _l(69, "1jn", "1 Juan", "Primera carta de san Juan", 5, "NT", numero=1, bases=("juan", "san juan"), abrev=("1jn", "1 jn")),
    _l(70, "2jn", "2 Juan", "Segunda carta de san Juan", 1, "NT", numero=2, bases=("juan", "san juan"), abrev=("2jn", "2 jn")),
    _l(71, "3jn", "3 Juan", "Tercera carta de san Juan", 1, "NT", numero=3, bases=("juan", "san juan"), abrev=("3jn", "3 jn")),
    _l(72, "jds", "Judas", "Carta de san Judas", 1, "NT", bases=("judas",), abrev=("jds", "jud")),
    _l(73, "ap", "Apocalipsis", "Apocalipsis", 22, "NT", bases=("apocalipsis",), abrev=("ap", "apoc")),
)

POR_ID: dict[str, Libro] = {lib.id: lib for lib in LIBROS}


def _construir_exactos() -> dict[str, Libro]:
    exactos: dict[str, Libro] = {}

    def agregar(clave: str, libro: Libro) -> None:
        k = normalizar(clave)
        previo = exactos.get(k)
        if previo is not None and previo.id != libro.id:
            raise RuntimeError(f"Alias ambiguo en el catálogo: '{k}' ({previo.id} y {libro.id})")
        exactos[k] = libro

    for libro in LIBROS:
        for clave in (libro.nombre, libro.hablado, *libro.abrev, *libro.alias):
            agregar(clave, libro)
        if libro.numero is None:
            for base in libro.bases:
                agregar(base, libro)
        else:
            for prefijo in _PREFIJOS[libro.numero]:
                for base in libro.bases:
                    agregar(f"{prefijo} {base}", libro)
    return exactos


_EXACTOS = _construir_exactos()


def obtener(id_libro: str) -> Libro:
    """Libro por id; error claro si no existe."""
    try:
        return POR_ID[id_libro.lower()]
    except KeyError:
        ids = ", ".join(lib.id for lib in LIBROS)
        raise KeyError(f"No conozco el libro '{id_libro}'. Ids válidos: {ids}") from None


def _ordinales_en(tokens: list[str]) -> set[int]:
    return {numero for tok in tokens for numero, formas in _ORDINALES.items() if tok in formas}


SECCION = "seccion"  # valor especial en [epub.titulos]: título de sección, no de libro


def detectar_libro_detalle(titulo: str, extra: dict[str, str] | None = None) -> tuple[Libro | None, str]:
    """Reconoce el libro a partir del texto de un título del EPUB y dice cómo lo hizo.

    Orden: overrides de config.toml → coincidencia exacta → coincidencia por palabra
    completa. Un ordinal solo cuenta si va ANTES del nombre: así 'PRIMERA EPÍSTOLA DE
    SAN JUAN' va a 1jn, pero 'GÉNESIS 1' sigue siendo Génesis. Un nombre de libro
    numerado sin ordinal ('SAMUEL', 'REYES') se toma como el primero de la serie, que es
    como lo titulan muchas ediciones; el informe lo señala para que puedas revisarlo.
    """
    t = normalizar(titulo)
    if not t:
        return None, "vacío"
    if extra:
        for clave, id_libro in extra.items():
            if normalizar(clave) == t:
                if id_libro == SECCION:
                    return None, SECCION
                return obtener(id_libro), "config"
    if t in _EXACTOS:
        return _EXACTOS[t], "exacto"
    candidatos: list[tuple[int, int, Libro, str]] = []  # (prioridad, largo, libro, modo)
    for libro in LIBROS:
        for base in libro.bases:
            if len(base) < 3:
                continue
            m = re.search(rf"(?<!\w){re.escape(base)}(?!\w)", t)
            if not m:
                continue
            previos = _ordinales_en(t[: m.start()].split())
            if libro.numero is None:
                if not previos:  # un ordinal delante del nombre apunta a un libro numerado
                    candidatos.append((2, len(base), libro, "nombre"))
            elif libro.numero in previos:
                candidatos.append((3, len(base), libro, "ordinal"))
            elif not previos and libro.numero == 1:
                candidatos.append((1, len(base), libro, "sin ordinal → primer libro"))
    if not candidatos:
        return None, "no reconocido"
    _p, _l, libro, modo = max(candidatos, key=lambda c: (c[0], c[1]))
    return libro, modo


def detectar_libro(titulo: str, extra: dict[str, str] | None = None) -> Libro | None:
    return detectar_libro_detalle(titulo, extra)[0]
