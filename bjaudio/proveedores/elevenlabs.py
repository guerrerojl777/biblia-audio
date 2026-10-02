"""ElevenLabs (REST /v1/text-to-speech/{voice_id}).

Datos de la documentación de ElevenLabs (verificados en octubre de 2026):
- `language_code` NO se admite con los modelos multilingual_v2; solo se envía con otros.
- `seed` hace el muestreo "lo más determinista posible", sin garantía.
- `previous_text` / `next_text` mejoran la continuidad al concatenar trozos.
- PCM/WAV a 44.1 kHz exige plan Pro; aquí se pide PCM a 24 kHz. Si tu plan rechaza el
  formato, se cae automáticamente a MP3 y se convierte con ffmpeg.
- Plan gratuito: ~10 000 créditos al mes (Multilingual v2 ≈ 1 crédito por carácter),
  uso no comercial con atribución. Alcanza para comparar voces, no para el día a día.
"""

from __future__ import annotations

import httpx

from .. import audio
from ..config import ConfigElevenLabs
from ..errores import ConfigError, ErrorProveedor, PresupuestoExcedido
from .base import TIMEOUT, Audio, Contexto, ProveedorTTS, peticion

URL_API = "https://api.elevenlabs.io"


class ElevenLabsTTS(ProveedorTTS):
    nombre = "elevenlabs"
    max_chars = 9000
    estocastico = True
    sample_rate = 24000

    def __init__(self, cfg: ConfigElevenLabs, api_key: str | None, transporte: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self.formato = cfg.formato
        self._api_key = api_key
        self._cliente = httpx.Client(
            base_url=URL_API,
            timeout=TIMEOUT,
            transport=transporte,
            headers={"xi-api-key": api_key or "", "Content-Type": "application/json"},
        )

    def listo(self) -> None:
        if not self._api_key:
            raise ConfigError("Falta ELEVENLABS_API_KEY en .env (cópialo de .env.example).")
        if not self.cfg.voz:
            raise ConfigError(
                "Falta [elevenlabs] voz (el voice_id) en config.toml. "
                "Lista las voces de tu cuenta con: python -m bjaudio voces --proveedor elevenlabs"
            )

    def firma(self) -> dict:
        c = self.cfg
        return {
            "proveedor": "elevenlabs", "voz": c.voz, "modelo": c.modelo, "estabilidad": c.estabilidad,
            "similitud": c.similitud, "estilo": c.estilo, "velocidad": c.velocidad, "semilla": c.semilla,
        }

    def _cuerpo(self, texto: str, contexto: Contexto) -> dict:
        c = self.cfg
        cuerpo: dict = {
            "text": texto,
            "model_id": c.modelo,
            "voice_settings": {
                "stability": c.estabilidad,
                "similarity_boost": c.similitud,
                "style": c.estilo,
                "use_speaker_boost": True,
                "speed": c.velocidad,
            },
            "seed": (c.semilla + contexto.variante) % 4294967296,
            "apply_text_normalization": "auto",
        }
        if c.idioma and "multilingual_v2" not in c.modelo:
            cuerpo["language_code"] = c.idioma
        if contexto.texto_anterior:
            cuerpo["previous_text"] = contexto.texto_anterior[-600:]
        if contexto.texto_siguiente:
            cuerpo["next_text"] = contexto.texto_siguiente[:600]
        return cuerpo

    def sintetizar(self, texto: str, contexto: Contexto) -> Audio:
        self.listo()
        cuerpo = self._cuerpo(texto, contexto)
        ruta = f"/v1/text-to-speech/{self.cfg.voz}"
        try:
            r = peticion(self._cliente, "POST", ruta, servicio="ElevenLabs TTS",
                         params={"output_format": self.formato}, json=cuerpo)
        except ErrorProveedor as e:
            if "output_format" in str(e) and self.formato.startswith("pcm_"):
                self.formato = "mp3_44100_128"  # el plan no admite PCM: se cae a MP3
                r = peticion(self._cliente, "POST", ruta, servicio="ElevenLabs TTS",
                             params={"output_format": self.formato}, json=cuerpo)
            else:
                raise
        if self.formato.startswith("pcm_"):
            sr = int(self.formato.split("_")[1])
            wav = audio.pcm_a_wav(r.content, sr)
        else:
            wav = audio.convertir(r.content, self.sample_rate)
        cargo = r.headers.get("character-cost") or r.headers.get("x-character-count")
        return Audio(
            wav=wav,
            caracteres=int(cargo) if cargo and cargo.isdigit() else len(texto),
            id_peticion=r.headers.get("request-id"),
        )

    def cuota(self) -> tuple[int, int] | None:
        """(usados, límite) del periodo actual según la API; None si no se puede consultar."""
        if not self._api_key:
            return None
        try:
            r = peticion(self._cliente, "GET", "/v1/user/subscription", servicio="ElevenLabs", intentos=2)
            datos = r.json()
            return int(datos["character_count"]), int(datos["character_limit"])
        except (ErrorProveedor, KeyError, ValueError, TypeError):
            return None

    def comprobar_cuota(self, caracteres: int) -> None:
        estado = self.cuota()
        if estado is None:
            return
        usados, limite = estado
        necesarios = int(caracteres * self.cfg.creditos_por_caracter)
        if usados + necesarios > limite:
            raise PresupuestoExcedido(
                f"ElevenLabs: necesitas ~{necesarios} créditos y te quedan {max(0, limite - usados)} "
                "este mes. No se llamó a la API."
            )

    def listar_voces(self) -> list[dict]:
        if not self._api_key:
            raise ConfigError("Falta ELEVENLABS_API_KEY en .env (cópialo de .env.example).")
        r = peticion(self._cliente, "GET", "/v2/voices", servicio="ElevenLabs", params={"page_size": 100})
        return r.json().get("voices", [])

    def cerrar(self) -> None:
        self._cliente.close()
