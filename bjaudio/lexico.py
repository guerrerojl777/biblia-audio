"""Léxico de pronunciación (lexico.tsv).

Formato, separado por tabuladores (las líneas con # son comentarios):

    palabra <TAB> cómo_escribirla_para_que_suene_bien <TAB> IPA_opcional

- Columna 2 (reescritura): se usa con cualquier motor. "-" o vacío = sin reescritura.
- Columna 3 (IPA): solo la usan motores que aceptan IPA (Deepgram Aura-2, en español
  e inglés). Si una palabra tiene IPA, el motor que la soporta usa el IPA y no la
  reescritura; los demás usan la reescritura si existe.

La coincidencia es por palabra completa y distingue mayúsculas (los nombres propios
van con mayúscula, y así no se toca una palabra común que se escriba igual).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .errores import TextoInvalido


@dataclass(frozen=True)
class Entrada:
    palabra: str
    reescritura: str | None
    ipa: str | None


@dataclass
class Lexico:
    entradas: dict[str, Entrada] = field(default_factory=dict)

    def _patron(self, palabras: list[str]) -> re.Pattern[str] | None:
        if not palabras:
            return None
        alternativas = "|".join(re.escape(p) for p in sorted(palabras, key=len, reverse=True))
        return re.compile(rf"(?<!\w)({alternativas})(?!\w)")

    def reescribir_comun(self, texto: str) -> str:
        """Etapa de plan: reescrituras de entradas SIN IPA (valen para cualquier motor)."""
        mapa = {e.palabra: e.reescritura for e in self.entradas.values() if e.reescritura and not e.ipa}
        patron = self._patron(list(mapa))
        return patron.sub(lambda m: mapa[m.group(1)], texto) if patron else texto

    def reescribir_sin_ipa(self, texto: str) -> str:
        """Etapa de proveedor sin IPA: entradas con IPA que además traen reescritura."""
        mapa = {e.palabra: e.reescritura for e in self.entradas.values() if e.ipa and e.reescritura}
        patron = self._patron(list(mapa))
        return patron.sub(lambda m: mapa[m.group(1)], texto) if patron else texto

    def con_ipa(self) -> dict[str, str]:
        return {e.palabra: e.ipa for e in self.entradas.values() if e.ipa}


def cargar_lexico(ruta: Path) -> Lexico:
    lexico = Lexico()
    ruta = Path(ruta)
    if not ruta.exists():
        return lexico
    for n, cruda in enumerate(ruta.read_text(encoding="utf-8").splitlines(), start=1):
        if not cruda.strip() or cruda.lstrip().startswith("#"):
            continue
        partes = [p.strip() for p in cruda.split("\t")]
        if len(partes) < 2 or not partes[0]:
            raise TextoInvalido(
                f"{ruta}:{n}: usa TABULADORES entre columnas: palabra<TAB>reescritura[<TAB>IPA]."
            )
        palabra = partes[0]
        reescritura = partes[1] if len(partes) > 1 and partes[1] not in ("", "-") else None
        ipa = partes[2] if len(partes) > 2 and partes[2] not in ("", "-") else None
        if reescritura is None and ipa is None:
            raise TextoInvalido(f"{ruta}:{n}: '{palabra}' no tiene ni reescritura ni IPA.")
        if ipa and len(ipa) > 128:
            raise TextoInvalido(f"{ruta}:{n}: el IPA de '{palabra}' supera 128 caracteres (límite de Deepgram).")
        lexico.entradas[palabra] = Entrada(palabra, reescritura, ipa)
    return lexico
