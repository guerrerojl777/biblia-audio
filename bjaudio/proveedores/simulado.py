"""Proveedor simulado: tonos en lugar de voz. Cuesta $0 y no usa red.

Sirve para probar de punta a punta la extracción, el plan, el ensamblado y el MP3
antes de gastar un solo carácter de crédito. Cada palabra es un tono cuya duración
depende de su largo; el ASR simulado reconstruye las mismas marcas de tiempo.
"""

from __future__ import annotations

from .. import audio
from ..normalizar import tokenizar
from .base import Audio, Contexto, ProveedorTTS

SR = 24000
INICIO = 0.20  # segundos de silencio antes de la primera palabra


def duracion_palabra(token: str) -> float:
    return 0.12 + 0.05 * len(token)


HUECO = 0.06


def linea_de_tiempo(texto: str) -> list[tuple[str, float, float]]:
    t = INICIO
    salida = []
    for token in tokenizar(texto):
        d = duracion_palabra(token)
        salida.append((token, t, t + d))
        t += d + HUECO
    return salida


class SimuladoTTS(ProveedorTTS):
    nombre = "simulado"
    max_chars = 100_000
    sample_rate = SR

    def firma(self) -> dict:
        return {"proveedor": "simulado", "version": 1}

    def sintetizar(self, texto: str, contexto: Contexto) -> Audio:
        partes = [audio.silencio(int(INICIO * 1000), SR)]
        for _token, inicio, fin in linea_de_tiempo(texto):
            partes.append(audio.tono(240, fin - inicio, SR))
            partes.append(audio.silencio(int(HUECO * 1000), SR))
        partes.append(audio.silencio(200, SR))
        return Audio(wav=audio.pcm_a_wav(b"".join(partes), SR), caracteres=len(texto))
