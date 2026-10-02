from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from bjaudio.config import Config
from bjaudio.lexico import Entrada, Lexico
from bjaudio.libros import obtener
from bjaudio.normalizar import numeros_a_palabras, tokenizar
from bjaudio.plan import planificar
from bjaudio.texto import parsear


def _cfg(**plan) -> Config:
    cfg = Config(raiz=Path("."))
    return replace(cfg, plan=replace(cfg.plan, **plan)) if plan else cfg


def _frase(n: int) -> str:
    return f"Esta es la oración número {n} y tiene varias palabras para ocupar espacio en el trozo."


def test_anuncio_y_pausas_de_parrafo():
    cap = parsear("# gn 1\n1 Uno.\n2 Dos.\n\n3 Tres.\n")
    trozos = planificar(cap, obtener("gn"), _cfg(), Lexico(), 2000)
    assert trozos[0].anuncio and trozos[0].texto == "Génesis. Capítulo uno."
    assert [t.texto for t in trozos[1:]] == ["Uno. Dos.", "Tres."]
    cfg = _cfg()
    assert trozos[1].pausa_ms == cfg.pausas.parrafo
    assert trozos[-1].pausa_ms == cfg.pausas.final


def test_nunca_supera_el_maximo_y_corta_en_oracion():
    lineas = ["# gn 2"] + [f"{i} {_frase(i)}" for i in range(1, 40)]
    cap = parsear("\n".join(lineas))
    trozos = planificar(cap, obtener("gn"), _cfg(objetivo_chars=300, max_chars=700), Lexico(), 2000)
    cuerpo = [t for t in trozos if not t.anuncio]
    assert all(t.caracteres <= 700 for t in trozos)
    assert all(t.texto.endswith(".") for t in cuerpo)
    # ningún versículo se pierde ni se duplica
    assert [v for t in cuerpo for v, _ in t.versos] == [str(i) for i in range(1, 40)]


def test_versiculo_gigante_se_parte():
    largo = " ".join(_frase(i) for i in range(60))  # ~5000 caracteres en un solo versículo
    cap = parsear(f"# est 8\n9 {largo}\n")
    trozos = planificar(cap, obtener("est"), _cfg(max_chars=1500, objetivo_chars=600), Lexico(), 2000)
    cuerpo = [t for t in trozos if not t.anuncio]
    assert len(cuerpo) >= 4 and all(t.caracteres <= 1500 for t in cuerpo)
    assert cuerpo[0].versos == [("9", 0)] and all(not t.versos for t in cuerpo[1:])
    assert " ".join(t.texto for t in cuerpo) == numeros_a_palabras(largo)  # "número 7" → "número siete"


def test_poesia_lleva_coma_y_salto():
    cap = parsear("# sal 1\n1 Dichoso quien camina\n/ por la senda recta.\n")
    trozos = planificar(cap, obtener("sal"), _cfg(), Lexico(), 2000)
    assert trozos[0].texto == "Salmo uno."
    assert trozos[1].texto == "Dichoso quien camina,\npor la senda recta."


def test_indices_de_versiculo_apuntan_a_su_primera_palabra():
    cap = parsear("# mt 5\n1 Viendo la multitud subió al monte.\n2 Y abriendo su boca enseñaba.\n3 Dichosos los pobres.\n")
    trozos = planificar(cap, obtener("mt"), _cfg(), Lexico(), 2000)
    t = trozos[1]
    tokens = tokenizar(t.texto)
    assert [tokens[i] for _, i in t.versos] == ["viendo", "y", "dichosos"]


def test_lexico_reescritura_y_simbolos():
    lex = Lexico({"Qohélet": Entrada("Qohélet", "Coélet", None)})
    cap = parsear("# qo 1\n1 Palabras de Qohélet* [hijo] de David.\n")
    trozos = planificar(cap, obtener("qo"), _cfg(), lex, 2000)
    assert trozos[1].texto == "Palabras de Coélet hijo de David."
