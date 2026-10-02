from __future__ import annotations

import json

import httpx
import pytest

from bjaudio import audio
from bjaudio.asr import DeepgramASR
from bjaudio.config import Config, ConfigDeepgram, ConfigElevenLabs
from bjaudio.errores import ConfigError, ErrorProveedor
from bjaudio.lexico import Entrada, Lexico
from bjaudio.proveedores import Contexto
from bjaudio.proveedores import base as base_mod
from bjaudio.proveedores.deepgram import DeepgramTTS
from bjaudio.proveedores.elevenlabs import ElevenLabsTTS

WAV = audio.pcm_a_wav(audio.tono(240, 0.3, 24000), 24000)


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    monkeypatch.setattr(base_mod.time, "sleep", lambda _s: None)


def test_deepgram_peticion_correcta():
    vistas = []

    def manejador(req: httpx.Request) -> httpx.Response:
        vistas.append(req)
        return httpx.Response(200, content=WAV, headers={"dg-char-count": "11", "dg-request-id": "abc"})

    tts = DeepgramTTS(ConfigDeepgram(voz="aura-2-javier-es", velocidad=0.95), "clave", httpx.MockTransport(manejador))
    r = tts.sintetizar("Hola mundo.", Contexto())
    req = vistas[0]
    assert req.url.path == "/v1/speak"
    assert dict(req.url.params) == {"model": "aura-2-javier-es", "encoding": "linear16", "container": "wav",
                                    "sample_rate": "24000", "speed": "0.95"}
    assert req.headers["authorization"] == "Token clave"
    assert json.loads(req.content) == {"text": "Hola mundo."}
    assert r.caracteres == 11 and r.id_peticion == "abc" and r.wav == WAV


def test_deepgram_ipa_en_linea():
    tts = DeepgramTTS(ConfigDeepgram(), "k")
    lex = Lexico({"Yahvé": Entrada("Yahvé", None, "ʝaβˈe")})
    texto = tts.preparar_texto("Habló Yahvé a Moisés.", lex)
    assert texto == 'Habló \\{"word": "Yahvé", "pronounce": "ʝaβˈe"\\} a Moisés.'


def test_deepgram_error_4xx_no_se_reintenta():
    llamadas = []

    def manejador(req):
        llamadas.append(1)
        return httpx.Response(400, json={"err_code": "INVALID", "err_msg": "texto vacío"})

    tts = DeepgramTTS(ConfigDeepgram(), "k", httpx.MockTransport(manejador))
    with pytest.raises(ErrorProveedor, match="texto vacío"):
        tts.sintetizar("x", Contexto())
    assert len(llamadas) == 1


def test_deepgram_reintenta_429():
    respuestas = iter([httpx.Response(429, json={"err_msg": "lento"}), httpx.Response(200, content=WAV)])
    tts = DeepgramTTS(ConfigDeepgram(), "k", httpx.MockTransport(lambda req: next(respuestas)))
    assert tts.sintetizar("Hola.", Contexto()).wav == WAV


def test_deepgram_sin_clave_falla_al_usar():
    tts = DeepgramTTS(ConfigDeepgram(), None)
    with pytest.raises(ConfigError, match="DEEPGRAM_API_KEY"):
        tts.sintetizar("Hola.", Contexto())


def test_elevenlabs_peticion_y_pcm():
    vistas = []
    pcm = audio.tono(240, 0.2, 24000)

    def manejador(req):
        vistas.append(req)
        return httpx.Response(200, content=pcm)

    cfg = ConfigElevenLabs(voz="VOZ123")
    tts = ElevenLabsTTS(cfg, "k", httpx.MockTransport(manejador))
    r = tts.sintetizar("Hola.", Contexto(texto_anterior="Antes.", texto_siguiente="Después.", variante=2))
    req = vistas[0]
    cuerpo = json.loads(req.content)
    assert req.url.path == "/v1/text-to-speech/VOZ123"
    assert req.url.params["output_format"] == "pcm_24000"
    assert req.headers["xi-api-key"] == "k"
    assert cuerpo["model_id"] == "eleven_multilingual_v2" and "language_code" not in cuerpo
    assert cuerpo["seed"] == cfg.semilla + 2
    assert cuerpo["previous_text"] == "Antes." and cuerpo["next_text"] == "Después."
    assert audio.info_wav(r.wav)[0] == 24000


def test_elevenlabs_modelo_no_v2_envia_idioma():
    vistas = []

    def manejador(req):
        vistas.append(json.loads(req.content))
        return httpx.Response(200, content=b"\x00\x00" * 100)

    tts = ElevenLabsTTS(ConfigElevenLabs(voz="V", modelo="eleven_flash_v2_5"), "k", httpx.MockTransport(manejador))
    tts.sintetizar("Hola.", Contexto())
    assert vistas[0]["language_code"] == "es"


def test_elevenlabs_cae_a_mp3_si_el_plan_rechaza_pcm(tmp_path):
    destino = tmp_path / "m.mp3"
    audio.exportar_mp3(audio.tono(240, 0.5, 24000), 24000, destino, kbps=64,
                       loudnorm=(-18.0, -1.5, 11.0), etiquetas={})
    mp3 = destino.read_bytes()
    formatos = []

    def manejador(req):
        formatos.append(req.url.params["output_format"])
        if req.url.params["output_format"].startswith("pcm"):
            return httpx.Response(403, json={"detail": {"message": "output_format not allowed on your plan"}})
        return httpx.Response(200, content=mp3)

    tts = ElevenLabsTTS(ConfigElevenLabs(voz="V"), "k", httpx.MockTransport(manejador))
    r = tts.sintetizar("Hola.", Contexto())
    assert formatos == ["pcm_24000", "mp3_44100_128"]
    assert audio.info_wav(r.wav)[0] == 24000


def test_deepgram_asr_lee_palabras(tmp_path):
    respuesta = {"results": {"channels": [{"alternatives": [{"words": [
        {"word": "génesis", "start": 0.1, "end": 0.6}, {"word": "capítulo", "start": 0.7, "end": 1.2}]}]}]}}
    vistas = []

    def manejador(req):
        vistas.append(req)
        return httpx.Response(200, json=respuesta)

    cfg = Config(raiz=tmp_path, deepgram_api_key="k")
    asr = DeepgramASR(cfg, httpx.MockTransport(manejador))
    palabras = asr.transcribir(WAV, "Génesis. Capítulo uno.")
    assert [p.texto for p in palabras] == ["génesis", "capítulo"]
    assert vistas[0].url.params["language"] == "es" and vistas[0].url.params["model"] == "nova-3"
    assert vistas[0].headers["content-type"] == "audio/wav"
