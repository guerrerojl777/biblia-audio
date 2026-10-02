"""Tokenización común para planificar y verificar, y cifras → palabras para la voz.

La verificación compara palabras, no sonidos: el texto que se pidió decir contra lo que el
reconocedor de voz oyó. Ambos lados pasan por aquí para que la comparación sea justa:
minúsculas, sin tildes, sin puntuación, números a palabras y unas pocas formas canónicas.

Para la voz, las cantidades se escriben en palabras y concuerdan con el sustantivo que
sigue, como las leería una persona: «21 hombres» → «veintiún hombres», «675.000 ovejas» →
«seiscientas setenta y cinco mil ovejas», «el 3.º día» → «el tercer día».
"""

from __future__ import annotations

import re
import unicodedata

from num2words import num2words

# Cantidad con separador de miles. En el texto (español) el separador es el punto; el
# reconocedor de voz puede escribir "46,500", así que al comparar se acepta también la coma.
_RE_MILES_TEXTO = re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})+(?![\d]|[.,]\d)")
_RE_MILES_ASR = re.compile(r"(?<![\d.,])\d{1,3}(?:[.,]\d{3})+(?![\d]|[.,]\d)")
_RE_ORDINAL = re.compile(r"(?<![\w.,])(\d{1,3})(?:\.?([ºª°])|\.(er|ra|ro)\b)")
_RE_ENTERO = re.compile(r"(?<![\w.,])\d+(?![\w]|[.,]\d)")
_RE_SIGUIENTE = re.compile(r"\s+([^\W\d_]+)")

# Palabras tras las que un número no concuerda con nada («21 de ellos», «eran 21 en total»).
_FUNCIONALES = frozenset(
    "de del en y e o u a al por para con sin que los las el la lo se su sus según como entre hasta "
    "desde sobre contra tras ante bajo más menos cada era eran fue fueron estaba estaban había habían "
    "son es está están hay serán sería".split()
)
# Femeninos frecuentes que no terminan en -as.
_FEMENINOS = frozenset(
    "mujer mujeres ciudad ciudades generación generaciones nación naciones tribu tribus vez veces "
    "noche noches torre torres llave llaves fuente fuentes legión legiones región regiones parte "
    "partes gente gentes nave naves ave aves res reses red redes pared paredes flor flores ley leyes "
    "piel pieles imagen imágenes señal señales lámpara".split()
)
# Terminan en -as y son masculinos (los profetas, los levitas, los días…).
_MASCULINOS_EN_AS = frozenset("días mapas problemas temas sistemas idiomas programas dramas dilemas "
                              "enigmas esquemas papas escribas persas guardas".split())


def quitar_tildes(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _siguiente(texto: str, fin: int) -> str | None:
    """Palabra que sigue a un número, si concuerda con él (no una preposición ni un verbo)."""
    m = _RE_SIGUIENTE.match(texto, fin)
    if not m:
        return None
    palabra = m.group(1).lower()
    return None if palabra in _FUNCIONALES or len(palabra) < 3 else palabra


def es_femenino(palabra: str) -> bool:
    """Género por la forma (-a, -as) con las excepciones habituales; basta para concordar
    un número con el sustantivo que lo sigue."""
    if palabra in _FEMENINOS:
        return True
    plural = palabra if palabra.endswith("s") else palabra + "s"
    if not plural.endswith("as") or len(plural) < 4 or plural in _MASCULINOS_EN_AS:
        return False
    # los israelitas, los patriarcas, los profetas, los días; y verbos como «llevabas»
    return not plural.endswith(("itas", "istas", "arcas", "etas", "abas"))


def _concordar(palabras: str, siguiente: str | None) -> str:
    """Concordancia del número con el sustantivo que sigue. Solo cambia lo que va después del
    último «millón»: «doscientos millones de ovejas» no concuerda, «doscientas mil ovejas» sí."""
    if siguiente is None:
        return palabras
    m = re.match(r"(.*\bmill(?:ón|ones)\b ?)(.*)", palabras)
    cabeza, cola = (m.group(1), m.group(2)) if m else ("", palabras)
    if not cola:
        return palabras
    if es_femenino(siguiente):
        cola = re.sub(r"ientos\b", "ientas", cola)
        cola = re.sub(r"\b(veinti)?uno$", lambda x: f"{x.group(1) or ''}una", cola)
    else:
        cola = re.sub(r"\bveintiuno$", "veintiún", cola)
        cola = re.sub(r"\buno$", "un", cola)
    return cabeza + cola


def _ordinal(texto: str, m: re.Match[str]) -> str:
    palabras = num2words(int(m.group(1)), lang="es", to="ordinal")
    marca = m.group(2) or m.group(3)
    if marca in ("ª", "ra"):
        return re.sub(r"o\b", "a", palabras)
    siguiente = _siguiente(texto, m.end())
    if marca == "er" or (siguiente is not None and not es_femenino(siguiente)):
        # «el 1.er día», «el 3.º día» → primer, tercer (ante sustantivo masculino)
        palabras = re.sub(r"\b(prim|terc)ero$", r"\1er", palabras)
    return palabras


def numeros_a_palabras(texto: str) -> str:
    """Cantidades en cifras → palabras en español, para que ninguna voz las lea a su manera
    ("46.500" → "cuarenta y seis mil quinientos"; nunca "cuarenta y seis punto quinientos")."""
    texto = _RE_ORDINAL.sub(lambda m: _ordinal(texto, m), texto)

    def cantidad(m: re.Match[str], quitar_puntos: bool) -> str:
        n = int(m.group().replace(".", "")) if quitar_puntos else int(m.group())
        return _concordar(num2words(n, lang="es"), _siguiente(m.string, m.end()))

    texto = _RE_MILES_TEXTO.sub(lambda m: cantidad(m, True), texto)
    return _RE_ENTERO.sub(lambda m: cantidad(m, False), texto)


# Variantes que un reconocedor puede escribir distinto sin que el audio esté mal.
_CANONICAS = {
    "un": "uno",
    "una": "uno",
    "veintiun": "veintiuno",
    "veintiuna": "veintiuno",
    "primer": "primero",
    "tercer": "tercero",
}
_RE_NO_PALABRA = re.compile(r"[^\w\s]|_")


def tokenizar(texto: str) -> list[str]:
    texto = _RE_MILES_ASR.sub(lambda m: re.sub(r"[.,]", "", m.group()), texto)
    limpio = _RE_NO_PALABRA.sub(" ", quitar_tildes(texto.lower()))
    salida: list[str] = []
    for token in limpio.split():
        if token.isdigit():
            salida.extend(tokenizar(num2words(int(token), lang="es")))
        elif token.endswith("ientas"):  # doscientas = doscientos al comparar
            salida.append(token[:-2] + "os")
        else:
            salida.append(_CANONICAS.get(token, token))
    return salida
