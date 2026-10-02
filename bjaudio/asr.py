"""Reconocimiento de voz para VERIFICAR (no para producir): ¿dijo el motor lo que le pedimos?

Tres opciones:
- deepgram: Nova-3 en español por REST. Rápido; consume crédito (~$0.0043/min).
- whisper: faster-whisper local en CPU. $0, más lento. Requiere requirements-whisper.txt.
- simulado: devuelve el texto de referencia con tiempos sintéticos (para probar tuberías).

Mecanismo a tener presente: un reconocedor tiene un fuerte "modelo de lenguaje" y tiende
a escribir lo que DEBERÍA haberse dicho. Por eso detecta muy bien palabras que faltan o
sobran, y mal un nombre propio pronunciado raro. Lo segundo se cuida con el léxico.
"""

from __future__ import annotations

import io
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from . import audio
from .config import Config
from .errores import ConfigError, ErrorProveedor
from .proveedores.base import TIMEOUT, peticion

URL_LISTEN = "https://api.deepgram.com/v1/listen"


@dataclass
class Palabra:
    texto: str
    inicio: float
    fin: float


class ASR(ABC):
    nombre: str = ""

    def firma(self) -> dict:
        """Parámetros que cambian la transcripción (clave de su caché)."""
        return {"asr": self.nombre}

    def listo(self) -> None:
        """Lanza ConfigError si falta algo para poder transcribir."""

    @abstractmethod
    def transcribir(self, wav: bytes, referencia: str) -> list[Palabra]:
        ...

    def costo_usd(self, segundos: float) -> float:
        return 0.0

    def cerrar(self) -> None:
        pass


class DeepgramASR(ASR):
    nombre = "deepgram"

    def __init__(self, cfg: Config, transporte: httpx.BaseTransport | None = None):
        self.cfg = cfg.deepgram
        self._api_key = cfg.deepgram_api_key
        self._cliente = httpx.Client(
            timeout=TIMEOUT,
            transport=transporte,
            headers={"Authorization": f"Token {cfg.deepgram_api_key or ''}", "Content-Type": "audio/wav"},
        )

    def listo(self) -> None:
        if not self._api_key:
            raise ConfigError("Falta DEEPGRAM_API_KEY en .env para verificar con Deepgram.")

    def firma(self) -> dict:
        return {"asr": "deepgram", "modelo": self.cfg.asr_modelo, "idioma": self.cfg.asr_idioma}

    def transcribir(self, wav: bytes, referencia: str) -> list[Palabra]:
        self.listo()
        params = {"model": self.cfg.asr_modelo, "language": self.cfg.asr_idioma}
        r = peticion(self._cliente, "POST", URL_LISTEN, servicio="Deepgram ASR", params=params, content=wav)
        try:
            alternativa = r.json()["results"]["channels"][0]["alternatives"][0]
        except (KeyError, IndexError, ValueError) as e:
            raise ErrorProveedor(f"Deepgram ASR devolvió una respuesta inesperada: {e}") from e
        return [Palabra(w["word"], float(w["start"]), float(w["end"])) for w in alternativa.get("words", [])]

    def costo_usd(self, segundos: float) -> float:
        return segundos / 60 * self.cfg.asr_usd_por_min

    def cerrar(self) -> None:
        self._cliente.close()


class WhisperLocalASR(ASR):
    nombre = "whisper"

    def __init__(self, cfg: Config):
        self._cfg = cfg.whisper
        self._modelo = None  # se carga al primer uso: cargar el modelo tarda y ocupa RAM

    def firma(self) -> dict:
        return {"asr": "whisper", "modelo": self._cfg.modelo, "computo": self._cfg.computo}

    def listo(self) -> None:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            raise ConfigError("Para asr = 'whisper' instala: pip install -r requirements-whisper.txt") from None

    def _cargar(self):
        if self._modelo is None:
            self.listo()
            from faster_whisper import WhisperModel

            w = self._cfg
            self._modelo = WhisperModel(w.modelo, device=w.dispositivo, compute_type=w.computo)
        return self._modelo

    def transcribir(self, wav: bytes, referencia: str) -> list[Palabra]:
        # Solo los nombres propios como pista: darle el texto completo podría hacer que
        # "oiga" palabras que el audio no tiene, y entonces no detectaríamos omisiones.
        nombres = sorted(set(re.findall(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñü]{2,}\b", referencia)))
        pista = ", ".join(nombres[:40]) or None
        segmentos, _info = self._cargar().transcribe(
            io.BytesIO(wav), language="es", word_timestamps=True, vad_filter=False,
            initial_prompt=pista, condition_on_previous_text=False,
        )
        palabras: list[Palabra] = []
        for seg in segmentos:
            for w in seg.words or []:
                palabras.append(Palabra(w.word.strip(), float(w.start), float(w.end)))
        return palabras


class SimuladoASR(ASR):
    nombre = "simulado"

    def transcribir(self, wav: bytes, referencia: str) -> list[Palabra]:
        from .proveedores.simulado import linea_de_tiempo

        return [Palabra(t, a, b) for t, a, b in linea_de_tiempo(referencia)]


def crear_asr(cfg: Config, nombre: str | None = None) -> ASR | None:
    nombre = nombre or cfg.asr
    if nombre == "ninguno":
        return None
    if nombre == "deepgram":
        return DeepgramASR(cfg)
    if nombre == "whisper":
        return WhisperLocalASR(cfg)
    if nombre == "simulado":
        return SimuladoASR()
    raise ConfigError(f"ASR desconocido: {nombre}")


def segundos_de(wav: bytes) -> float:
    sr, _canales, _ancho, n = audio.info_wav(wav)
    return n / sr if sr else 0.0
