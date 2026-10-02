"""Caché de audio por contenido: misma voz + mismos parámetros + mismo texto = mismo archivo.

Es el equivalente de un idempotency store: reejecutar un capítulo solo paga los trozos
que cambiaron (porque editaste el texto o el léxico) o que nunca se generaron.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .texto import escribir_atomico


class CacheAudio:
    def __init__(self, directorio: Path):
        self.dir = Path(directorio)

    @staticmethod
    def clave(firma: dict, texto: str, variante: int = 0) -> str:
        datos = json.dumps({"firma": firma, "texto": texto, "variante": variante}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(datos.encode("utf-8")).hexdigest()[:32]

    def _ruta(self, proveedor: str, clave: str) -> Path:
        return self.dir / proveedor / clave[:2] / f"{clave}.wav"

    def existe(self, proveedor: str, clave: str) -> bool:
        return self._ruta(proveedor, clave).exists()

    def obtener(self, proveedor: str, clave: str) -> bytes | None:
        ruta = self._ruta(proveedor, clave)
        return ruta.read_bytes() if ruta.exists() else None

    def guardar(self, proveedor: str, clave: str, wav: bytes, meta: dict) -> None:
        ruta = self._ruta(proveedor, clave)
        escribir_atomico(ruta, wav)
        meta = {**meta, "guardado": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        escribir_atomico(ruta.with_suffix(".json"), json.dumps(meta, ensure_ascii=False, indent=2))

    # -- transcripciones de verificación: también cuestan, así que también se guardan
    def _ruta_asr(self, proveedor: str, clave: str, firma_asr: dict) -> Path:
        huella = hashlib.sha256(json.dumps(firma_asr, sort_keys=True).encode()).hexdigest()[:10]
        return self._ruta(proveedor, clave).with_suffix(f".asr-{huella}.json")

    def obtener_transcripcion(self, proveedor: str, clave: str, firma_asr: dict) -> list[list] | None:
        ruta = self._ruta_asr(proveedor, clave, firma_asr)
        if not ruta.exists():
            return None
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def guardar_transcripcion(self, proveedor: str, clave: str, firma_asr: dict, palabras: list[list]) -> None:
        escribir_atomico(self._ruta_asr(proveedor, clave, firma_asr), json.dumps(palabras, ensure_ascii=False))
