from __future__ import annotations

from bjaudio.asr import Palabra
from bjaudio.config import ConfigVerificacion
from bjaudio.normalizar import tokenizar
from bjaudio.verificacion import verificar

REF = ("Al principio la luz llenó la casa y la mesa estaba servida "
       "mientras el pan seguía tibio y dijo el vecino que haya fiesta hasta la noche")
VERSOS = [("1", 0), ("2", 7)]


def _palabras(tokens: list[str]) -> list[Palabra]:
    return [Palabra(t, 0.5 * i, 0.5 * i + 0.4) for i, t in enumerate(tokens)]


def test_audio_fiel_no_se_marca_y_da_tiempos():
    r = verificar(REF, VERSOS, _palabras(tokenizar(REF)), ConfigVerificacion(), 20.0)
    assert not r.marcado and r.wer == 0
    assert r.tiempos == {"1": 0.0, "2": 3.5}


def test_racha_de_omision_se_marca():
    tokens = tokenizar(REF)
    del tokens[9:13]  # se "salta" cuatro palabras seguidas
    r = verificar(REF, VERSOS, _palabras(tokens), ConfigVerificacion(), 20.0)
    assert r.marcado and r.racha_omision == 4
    assert "faltan 4" in r.motivo and r.faltantes


def test_errores_dispersos_del_reconocedor_no_se_marcan():
    tokens = tokenizar(REF)
    for i in (2, 10, 20):
        tokens[i] = tokens[i] + "x"  # sustituciones sueltas, típicas del ASR con nombres
    r = verificar(REF, VERSOS, _palabras(tokens), ConfigVerificacion(), 20.0)
    assert not r.marcado and r.sustituciones == 3


def test_racha_de_insercion_se_marca():
    tokens = tokenizar(REF)
    tokens[5:5] = ["bla", "bla", "bla", "bla", "bla"]
    r = verificar(REF, VERSOS, _palabras(tokens), ConfigVerificacion(), 20.0)
    assert r.marcado and r.racha_insercion == 5


def test_numeros_y_variantes_equivalen():
    r = verificar("Tenía 21 años y una hija.", [], _palabras(["tenía", "veintiún", "años", "y", "un", "hija"]),
                  ConfigVerificacion(), 5.0)
    assert r.wer == 0


def test_silencio_total_se_marca():
    r = verificar(REF, VERSOS, [], ConfigVerificacion(), 20.0)
    assert r.marcado and "no se oyó nada" in r.motivo
