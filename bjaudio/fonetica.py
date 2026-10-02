"""Pronunciación de la erre final: IPA del español por reglas y marcas para Deepgram.

Algunas voces sintéticas en español convierten la erre final en algo parecido a «rz»:
«mar» suena «marzo». La erre al final de sílaba es la posición más variable del español
(se asibila en México, los Andes o Costa Rica; se vuelve «l» o se aspira en el Caribe), y
un modelo entrenado con muchas voces aprende un promedio que no es ninguna de ellas.

Tres maneras de decirle al motor cómo sonar, para probar cuál le sirve (bja probar-erre):
- "suave": la palabra en IPA con erre simple [ɾ] al final (lo normativo: «mar» = [maɾ]).
- "fuerte": la palabra en IPA con erre múltiple [r] al final (una erre más marcada).
- "rr": se escribe «marr» en el texto que recibe el motor (sin IPA).

Solo cambia el texto que recibe el motor de voz: el .txt canónico y la verificación ven
«mar». El español se escribe casi como se pronuncia, así que unas pocas reglas dan el IPA
de casi cualquier palabra; aquí solo hace falta para las que terminan en «r».
"""

from __future__ import annotations

import re

MODOS_ERRE = ("", "suave", "fuerte", "rr")

_ACENTUADAS = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u"}
_VOCALES = set("aeiouáéíóúü")
_FUERTES = set("aeoáéó")
_ANTE_E_I = set("eiéí")
_IPA_BLOQUE = re.compile(r"\\\{.*?\\\}")
_PALABRA_ERRE = re.compile(r"(?<![\w\\])([^\W\d_]*[aeiouáéíóúAEIOUÁÉÍÓÚ][rR])(?![\w])")


def _segmentos(p: str, seseo: bool, final: str) -> list[tuple[str, str]]:
    """Palabra en minúsculas → [(símbolo, tipo)], tipo "C" consonante o una vocal ("a", "é"…)."""
    s: list[tuple[str, str]] = []
    i, n = 0, len(p)
    while i < n:
        c = p[i]
        sig = p[i + 1] if i + 1 < n else ""
        sig2 = p[i + 2] if i + 2 < n else ""
        if c in _VOCALES:
            s.append(("u" if c == "ü" else _ACENTUADAS.get(c, c), c))
        elif c == "c" and sig == "h":
            s.append(("tʃ", "C"))
            i += 1
        elif c == "l" and sig == "l":
            s.append(("ʝ", "C"))
            i += 1
        elif c == "r" and sig == "r":
            s.append(("r", "C"))
            i += 1
        elif c == "q" and sig == "u" and sig2 in _ANTE_E_I:
            s.append(("k", "C"))
            i += 1
        elif c == "g" and sig == "u" and sig2 in _ANTE_E_I:
            s.append(("ɡ", "C"))
            i += 1
        elif c == "c":
            s.append((("s" if seseo else "θ") if sig in _ANTE_E_I else "k", "C"))
        elif c == "z":
            s.append(("s" if seseo else "θ", "C"))
        elif c == "g":
            s.append(("x" if sig in _ANTE_E_I else "ɡ", "C"))
        elif c == "j":
            s.append(("x", "C"))
        elif c == "h":
            pass  # muda
        elif c == "ñ":
            s.append(("ɲ", "C"))
        elif c == "v":
            s.append(("b", "C"))
        elif c == "x":
            s.append(("ks", "C"))
        elif c == "q":
            s.append(("k", "C"))
        elif c == "y":
            if i == n - 1 or sig not in _VOCALES:
                s.append(("i", "i"))  # «rey», «muy»: vocal
            else:
                s.append(("ʝ", "C"))
        elif c == "r":
            if i == 0 or p[i - 1] in "nls":
                s.append(("r", "C"))  # «río», «honra», «Israel»: múltiple
            elif i == n - 1:
                s.append(("r" if final == "fuerte" else "ɾ", "C"))
            else:
                s.append(("ɾ", "C"))
        else:
            s.append((c, "C"))
        i += 1
    return s


def ipa_es(palabra: str, *, seseo: bool = True, final: str = "suave") -> str | None:
    """IPA de una palabra española, con la marca de acento justo antes de la vocal (como pide
    Aura-2). Las palabras de una sílaba van sin marca («por», «mar»): así el motor decide si
    la acentúa según la frase. None si la palabra no es solo letras."""
    p = palabra.lower()
    if not p.isalpha():
        return None
    seg = _segmentos(p, seseo, final)
    vocales = [k for k, (_, t) in enumerate(seg) if t != "C"]
    if not vocales:
        return None
    # Núcleos de sílaba: en cada grupo de vocales seguidas, las fuertes (a, e, o) y las
    # débiles con tilde (í, ú) son núcleo; una débil sin tilde junto a otra vocal es
    # semivocal (j, w), salvo en «ui», «iu», donde la última es el núcleo.
    nucleos: list[int] = []
    grupos: list[list[int]] = []
    for k in vocales:
        if grupos and grupos[-1][-1] == k - 1:
            grupos[-1].append(k)
        else:
            grupos.append([k])
    for g in grupos:
        fuertes = [k for k in g if seg[k][1] in _FUERTES or seg[k][1] in "íú"]
        nucleos.extend(fuertes if fuertes else [g[-1]])
    nucleos.sort()
    con_tilde = [k for k in nucleos if seg[k][1] in _ACENTUADAS]
    if con_tilde:
        tonica = con_tilde[0]
    elif p[-1] in "aeiouns" and len(nucleos) > 1:
        tonica = nucleos[-2]  # llana
    else:
        tonica = nucleos[-1]  # aguda (todas las que terminan en r sin tilde)
    salida = []
    for k, (simbolo, tipo) in enumerate(seg):
        if tipo != "C" and k not in nucleos:
            simbolo = "j" if simbolo == "i" else "w" if simbolo == "u" else simbolo
        if k == tonica and len(nucleos) > 1:
            salida.append("ˈ")
        salida.append(simbolo)
    return "".join(salida)


def _bloque(palabra: str, ipa: str) -> str:
    # Una sola barra invertida antes de cada llave: json.dumps la escapa al enviar.
    return '\\{"word": "%s", "pronounce": "%s"\\}' % (palabra, ipa)


def marcar_erre_final(texto: str, modo: str, *, seseo: bool = True, excluir: frozenset[str] = frozenset()) -> str:
    """Aplica el modo a cada palabra terminada en «r» que no esté ya dentro de una marca de
    IPA ni en `excluir` (las del léxico mandan)."""
    if not modo:
        return texto

    def una(m: re.Match[str]) -> str:
        palabra = m.group(1)
        if palabra in excluir:
            return palabra
        if modo == "rr":
            return palabra + palabra[-1]
        ipa = ipa_es(palabra, seseo=seseo, final=modo)
        return _bloque(palabra, ipa) if ipa else palabra

    partes = []
    ultimo = 0
    for b in _IPA_BLOQUE.finditer(texto):
        partes.append(_PALABRA_ERRE.sub(una, texto[ultimo:b.start()]))
        partes.append(b.group())
        ultimo = b.end()
    partes.append(_PALABRA_ERRE.sub(una, texto[ultimo:]))
    return "".join(partes)


# Frase inventada con erre final en todas las posiciones: ante coma, ante consonante, ante
# vocal, al final, y en una palabra átona («por»), para oír si el arreglo estropea algo.
FRASE_ERRE = ("El río corre por el valle hacia el mar, y el mar nunca descansa. "
              "Quiero ver la luz y oír el rumor del viento al amanecer.")

OPCIONES_ERRE = (
    ("", "como ahora (sin cambios)"),
    ("suave", "erre simple en IPA [ɾ]"),
    ("fuerte", "erre múltiple en IPA [r]"),
    ("rr", "«rr» escrita: «marr»"),
)


def variantes_erre(seseo: bool, frase: str = FRASE_ERRE) -> list[tuple[str, str, str]]:
    """(modo, descripción, texto para el motor) de cada opción, en orden."""
    return [(modo, descripcion, marcar_erre_final(frase, modo, seseo=seseo)) for modo, descripcion in OPCIONES_ERRE]


def sin_marcas(texto: str) -> str:
    """Texto que factura Deepgram: cada marca de IPA cuenta como su palabra."""
    return _IPA_BLOQUE.sub(lambda b: re.search(r'"word": "([^"]*)"', b.group()).group(1), texto)


def partir_peticion(texto: str, limite: int) -> list[str]:
    """Si las marcas de IPA alargan un trozo más allá de lo que acepta el motor, se pide en
    partes: por fin de oración, si no por ; : , y en último caso por espacios. Nunca se corta
    dentro de una marca de IPA."""
    if len(texto) <= limite:
        return [texto]
    protegidos = [(b.start(), b.end()) for b in _IPA_BLOQUE.finditer(texto)]

    def libre(pos: int) -> bool:
        return not any(a < pos < b for a, b in protegidos)

    medio = len(texto) // 2
    for patron in (r"[.!?…»”]\s+", r"[;:]\s+", r",\s+", r"\s+"):
        cortes = [m.end() for m in re.finditer(patron, texto) if libre(m.end()) and 0 < m.end() < len(texto)]
        if cortes:
            corte = min(cortes, key=lambda c: abs(c - medio))
            izquierda, derecha = texto[:corte].rstrip(), texto[corte:].lstrip()
            if izquierda and derecha:
                return partir_peticion(izquierda, limite) + partir_peticion(derecha, limite)
    raise ValueError("No encontré dónde partir el texto sin cortar una marca de IPA.")
