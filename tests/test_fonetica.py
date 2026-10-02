"""Erre final: IPA por reglas, marcas para Deepgram, peticiones partidas y laboratorio."""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest
from typer.testing import CliRunner

from bjaudio import audio
from bjaudio.cli import app
from bjaudio.config import ConfigDeepgram
from bjaudio.errores import ConfigError
from bjaudio.fonetica import FRASE_ERRE, ipa_es, marcar_erre_final, partir_peticion, sin_marcas, variantes_erre
from bjaudio.lexico import Entrada, Lexico
from bjaudio.proveedores import Contexto
from bjaudio.proveedores import base as base_mod
from bjaudio.proveedores.deepgram import DeepgramTTS

WAV = audio.pcm_a_wav(audio.tono(240, 0.3, 24000), 24000)


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    monkeypatch.setattr(base_mod.time, "sleep", lambda _s: None)


@pytest.mark.parametrize("palabra, america, espana", [
    ("mar", "maɾ", "maɾ"),            # una sílaba: sin marca de acento
    ("por", "poɾ", "poɾ"),            # átona: el motor decide en la frase
    ("decir", "desˈiɾ", "deθˈiɾ"),    # seseo / distinción
    ("oír", "oˈiɾ", "oˈiɾ"),          # hiato con tilde
    ("mujer", "muxˈeɾ", "muxˈeɾ"),
    ("construir", "konstɾwˈiɾ", "konstɾwˈiɾ"),
    ("mártir", "mˈaɾtiɾ", "mˈaɾtiɾ"),  # tilde en otra sílaba
    ("confiar", "konfjˈaɾ", "konfjˈaɾ"),
    ("honrar", "onrˈaɾ", "onrˈaɾ"),    # erre múltiple tras n; h muda
    ("averiguar", "abeɾiɡwˈaɾ", "abeɾiɡwˈaɾ"),
    ("llorar", "ʝoɾˈaɾ", "ʝoɾˈaɾ"),
    ("quitar", "kitˈaɾ", "kitˈaɾ"),
    ("Baltasar", "baltasˈaɾ", "baltasˈaɾ"),
])
def test_ipa_por_reglas(palabra, america, espana):
    assert ipa_es(palabra, seseo=True) == america
    assert ipa_es(palabra, seseo=False) == espana


def test_ipa_erre_fuerte_solo_cambia_la_final():
    assert ipa_es("dormir", final="fuerte") == "doɾmˈir"
    assert ipa_es("mar", final="fuerte") == "mar"
    assert ipa_es("3x") is None


def test_marcas_por_modo():
    texto = "Van al mar, y el mar nunca se llena por eso."
    suave = marcar_erre_final(texto, "suave")
    assert suave.count('\\{"word": "mar", "pronounce": "maɾ"\\}') == 2
    assert '\\{"word": "por", "pronounce": "poɾ"\\}' in suave and "llena" in suave
    assert marcar_erre_final(texto, "rr") == "Van al marr, y el marr nunca se llena porr eso."
    assert marcar_erre_final(texto, "") == texto
    for modo in ("suave", "fuerte", "rr"):
        assert sin_marcas(marcar_erre_final(texto, modo)).replace("rr", "r") == texto  # se factura lo mismo


def test_marcas_respetan_el_lexico_y_las_marcas_existentes():
    previo = 'Dijo \\{"word": "Ester", "pronounce": "estˈer"\\} al mar.'
    salida = marcar_erre_final(previo, "suave", excluir=frozenset({"Ester"}))
    assert salida.count("\\{") == 2 and '"pronounce": "estˈer"' in salida and '"word": "mar"' in salida


def test_partir_peticion_no_corta_marcas():
    texto = marcar_erre_final(" ".join(["Quiero ver el mar al amanecer."] * 40), "suave")
    partes = partir_peticion(texto, 2000)
    assert len(partes) >= 2 and all(len(p) <= 2000 for p in partes)
    assert all(p.count("\\{") == p.count("\\}") for p in partes)
    assert " ".join(partes) == texto


def test_variantes_del_laboratorio():
    opciones = variantes_erre(seseo=True)
    assert [m for m, _d, _t in opciones] == ["", "suave", "fuerte", "rr"]
    assert opciones[0][2] == FRASE_ERRE and len({t for _m, _d, t in opciones}) == 4


def test_deepgram_aplica_la_erre_final_y_el_lexico():
    tts = DeepgramTTS(ConfigDeepgram(voz="aura-2-gloria-es", erre_final="suave"), "k")
    lex = Lexico({"Cohélet": Entrada("Cohélet", None, "koˈelet")})
    texto = tts.preparar_texto("Dijo Cohélet: hacer.", lex)
    assert texto == ('Dijo \\{"word": "Cohélet", "pronounce": "koˈelet"\\}: '
                     '\\{"word": "hacer", "pronounce": "asˈeɾ"\\}.')
    espana = DeepgramTTS(ConfigDeepgram(voz="aura-2-alvaro-es", erre_final="suave"), "k")
    assert espana.preparar_texto("hacer", Lexico()) == '\\{"word": "hacer", "pronounce": "aθˈeɾ"\\}'
    sin = DeepgramTTS(ConfigDeepgram(voz="aura-2-gloria-es"), "k")
    assert sin.preparar_texto("hacer", Lexico()) == "hacer"


def test_deepgram_parte_la_peticion_si_las_marcas_la_alargan():
    vistas = []

    def manejador(req: httpx.Request) -> httpx.Response:
        texto = json.loads(req.content)["text"]
        vistas.append(texto)
        return httpx.Response(200, content=WAV, headers={"dg-char-count": str(len(sin_marcas(texto)))})

    tts = DeepgramTTS(ConfigDeepgram(erre_final="suave"), "k", httpx.MockTransport(manejador))
    texto = tts.preparar_texto(" ".join(["Quiero ver el mar al amanecer."] * 40), Lexico())
    assert len(texto) > 2000
    r = tts.sintetizar(texto, Contexto())
    assert len(vistas) >= 2 and all(len(v) <= 2000 for v in vistas)
    assert r.caracteres == sum(len(sin_marcas(v)) for v in vistas)
    assert audio.duracion(audio.a_pcm(r.wav, 24000), 24000) == pytest.approx(0.3 * len(vistas), abs=0.01)


def test_config_valida_erre_final(proyecto):
    from bjaudio.config import validar

    validar(replace(proyecto, deepgram=replace(proyecto.deepgram, erre_final="fuerte")))
    with pytest.raises(ConfigError, match="erre_final"):
        validar(replace(proyecto, deepgram=replace(proyecto.deepgram, erre_final="doble")))


def test_probar_erre_genera_un_mp3_con_las_cuatro_opciones(proyecto, monkeypatch):
    import bjaudio.cli as cli

    vistas = []

    def manejador(req: httpx.Request) -> httpx.Response:
        texto = json.loads(req.content)["text"]
        vistas.append((dict(req.url.params)["model"], texto))
        return httpx.Response(200, content=WAV, headers={"dg-char-count": str(len(sin_marcas(texto)))})

    def crear(cfg, nombre=None):
        return DeepgramTTS(cfg.deepgram, "clave", httpx.MockTransport(manejador))

    monkeypatch.setattr(cli, "crear_tts", crear)
    r = CliRunner().invoke(app, ["--config", str(proyecto.ruta_config), "probar-erre", "--voz", "gloria"])
    assert r.exit_code == 0, r.output
    assert len(vistas) == 4 and {m for m, _t in vistas} == {"aura-2-gloria-es"}
    assert vistas[0][1].startswith("Opción uno. El río") and "\\{" not in vistas[0][1]
    assert '"pronounce": "maɾ"' in vistas[1][1] and '"pronounce": "mar"' in vistas[2][1] and "marr" in vistas[3][1]
    assert (proyecto.dir_salida / "muestras" / "erre-deepgram-aura-2-gloria-es.mp3").exists()
    assert 'erre_final = "suave"' in r.output
