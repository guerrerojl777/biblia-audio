"""Libro de gastos (append-only, JSONL) y guardia de presupuesto.

Regla: ninguna llamada a una API de pago ocurre sin antes comprobar que el gasto
estimado cabe en lo disponible. Si no cabe, se aborta ANTES de llamar.

Limitación honesta: este libro solo ve lo que gasta esta herramienta. Si usas la
consola de Deepgram o ElevenLabs por fuera, actualiza `credito_usd` en config.toml
con el saldo real que muestre tu consola.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class LibroGastos:
    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)

    def registrar(self, proveedor: str, tipo: str, unidades: float, usd: float, referencia: str = "") -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        fila = {
            "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "proveedor": proveedor,
            "tipo": tipo,  # "tts" (unidades = caracteres) o "asr" (unidades = segundos)
            "unidades": unidades,
            "usd": round(usd, 6),
            "ref": referencia,
        }
        with self.ruta.open("a", encoding="utf-8") as f:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")

    def filas(self) -> list[dict]:
        if not self.ruta.exists():
            return []
        salida = []
        for linea in self.ruta.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                try:
                    salida.append(json.loads(linea))
                except json.JSONDecodeError:
                    continue  # una línea corrupta no debe tumbar el resto
        return salida

    def total_usd(self, proveedor: str) -> float:
        return sum(f["usd"] for f in self.filas() if f["proveedor"] == proveedor)

    def unidades_mes(self, proveedor: str, tipo: str, ahora: datetime | None = None) -> float:
        ahora = ahora or datetime.now(timezone.utc)
        prefijo = ahora.strftime("%Y-%m")
        return sum(
            f["unidades"] for f in self.filas()
            if f["proveedor"] == proveedor and f["tipo"] == tipo and f["fecha"].startswith(prefijo)
        )
