"""Extracción e inspección sobre un EPUB con la estructura de una BJ convertida con Sigil."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from bjaudio.cli import app
from bjaudio.config import CAPITULO_DEFECTO, Config, ConfigEpub, actualizar_config, cargar_config
from bjaudio.epub import Epub
from bjaudio.errores import ConfigError
from bjaudio.extraccion import documentos_de_libro, extraer, mapa_documentos
from bjaudio.inspeccion import calidad_versos, inspeccionar, margenes_superiores, puntaje_capitulos
from bjaudio.libros import detectar_libro_detalle
from bjaudio.texto import LINEA, PARRAFO, SECCION, VERSICULO

from .epub_bj import CSS, crear_epub_bj

SUGERIDA = ConfigEpub(
    capitulo=f"b, {CAPITULO_DEFECTO}",
    bloque_corto_chars=100,
    estrofa=".top05",
)


@pytest.fixture
def epub_bj(tmp_path) -> Path:
    (tmp_path / "libros").mkdir()
    return crear_epub_bj(tmp_path / "libros" / "biblia.epub")


@pytest.fixture
def proyecto_bj(tmp_path, epub_bj) -> Config:
    (tmp_path / "config.toml").write_text(
        '# mi configuración\nproveedor = "simulado"\nasr = "simulado"\n\n[epub]\narchivo = "libros/biblia.epub"\n\n'
        '[deepgram]\nvoz = "aura-2-alvaro-es"        # España\n',
        encoding="utf-8",
    )
    return cargar_config(tmp_path / "config.toml")


def _extraer(epub_bj, cfg=SUGERIDA, libro=None):
    with Epub(epub_bj) as e:
        return extraer(e, cfg, libro)


# ------------------------------------------------------------------ títulos
@pytest.mark.parametrize("titulo, esperado, modo", [
    ("SAMUEL", "1s", "sin ordinal → primer libro"),
    ("REYES", "1r", "sin ordinal → primer libro"),
    ("LOS LIBROS DE LAS CRÓNICAS", "1cro", "sin ordinal → primer libro"),
    ("LIBRO SEGUNDO DE LOS REYES *", "2r", "ordinal"),
    ("LIBRO PRIMERO DE LOS MACABEOS", "1m", "ordinal"),
    ("EPÍSTOLA DE SAN JUDAS", "jds", "nombre"),
    ("TERCERA EPÍSTOLA DE SAN JUAN", "3jn", "exacto"),
    ("EVANGELIO SEGÚN SAN JUAN", "jn", "exacto"),
    ("LOS LIBROS DE JOSUÉ, JUECES, RUT, SAMUEL Y REYES", "jc", "nombre"),
])
def test_titulos_de_una_bj(titulo, esperado, modo):
    libro, m = detectar_libro_detalle(titulo)
    assert (libro.id if libro else None, m) == (esperado, modo)


def test_titulo_como_seccion_por_configuracion():
    libro, modo = detectar_libro_detalle("PRIMERA PARTE", {"PRIMERA PARTE": "seccion"})
    assert libro is None and modo == "seccion"


# ------------------------------------------------------------------ extracción
def test_eclesiastes_completo_con_la_configuracion_sugerida(epub_bj):
    res = _extraer(epub_bj, libro="qo")
    caps = {c.numero: c for c in res.capitulos}
    assert sorted(caps) == list(range(1, 13))
    uno = caps[1]
    assert not uno.explicito  # sin marca: se asumió al ver el versículo 1
    assert [s.titulo for s in uno.secciones] == ["Título", "Prólogo"]  # "Título" iba antes del capítulo
    assert uno.versiculos == ["1", "2", "3", "4"]
    assert [u.ruptura for u in uno.unidades] == [SECCION, SECCION, LINEA, VERSICULO, LINEA, PARRAFO, LINEA]
    assert uno.a_texto() == (
        "# qo 1\n\n## Título\n1 Palabras del predicador, hijo del rey.\n\n## Prólogo\n"
        "2 ¡Humo y más humo!, dice el predicador,\n/ ¡humo y más humo, todo es humo!\n"
        "3 ¿Qué gana la gente\n/ con todo el trabajo que hace?\n\n"
        "4 Una generación se va,\n/ otra generación viene.\n"
    )
    # el título "El tiempo" va antes del párrafo con el <b>3</b>: pertenece al capítulo 3
    assert [s.titulo for s in caps[2].secciones] == []
    assert [s.titulo for s in caps[3].secciones] == ["El tiempo"]
    todo = " ".join(u.texto for c in res.capitulos for u in c.unidades)
    assert "editor" not in todo and "Introducción" not in todo and "*" not in todo
    # la referencia "(3 1-8)" de la introducción no creó un capítulo; el "12" falso perdió contra el real
    assert any("qo 3" in d and "part0002" in d for d in res.descartados)
    # el "12" de la introducción solo tenía una llamada de nota numérica sin texto detrás
    assert any("qo 12" in d and "part0002" in d for d in res.descartados)
    assert caps[12].origen.endswith("part0003.xhtml") and caps[12].versiculos == ["1", "2", "3"]


def test_notas_titulos_y_libros_de_un_capitulo(epub_bj):
    res = _extraer(epub_bj)
    libros = sorted({c.libro for c in res.capitulos})
    assert libros == ["1s", "flm", "qo"]
    assert [c.numero for c in res.capitulos if c.libro == "flm"] == [1]
    modos = {t.texto: t.modo for t in res.titulos}
    assert modos["Notas | Eclesiastés"] == "ignorado"
    assert modos["Notas marginales | Eclesiastés"] == "ignorado"
    assert modos["SAMUEL"] == "sin ordinal → primer libro"
    # las marcas del índice inicial no tienen libro: un solo aviso agregado, no uno por marca
    fuera = [a for a in res.avisos if "BIBLIA DE JERUSALÉN" in a]
    assert len(fuera) == 1 and fuera[0].startswith("2 marca(s)")
    # nada de las notas se coló en ningún capítulo
    assert "no debe leerse" not in " ".join(u.texto for c in res.capitulos for u in c.unidades)


def test_sin_configuracion_solo_sale_lo_que_el_capitulo_1_implicito_atrapa(epub_bj):
    res = _extraer(epub_bj, ConfigEpub(), "qo")
    assert [c.numero for c in res.capitulos] == [1]  # el resto de capítulos queda dentro del 1
    assert any("número suelto" in a for a in res.avisos)


def test_mapa_y_documentos_de_un_libro(epub_bj):
    with Epub(epub_bj) as e:
        mapa = mapa_documentos(e, ConfigEpub())
    assert documentos_de_libro(mapa, "qo") == ["OEBPS/Text/part0002.xhtml", "OEBPS/Text/part0003.xhtml"]
    assert documentos_de_libro(mapa, "1s") == ["OEBPS/Text/part0004.xhtml"]


# ------------------------------------------------------------------ deducción
def test_formas_de_secuencia():
    assert puntaje_capitulos([2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], 12) > 0.9
    assert puntaje_capitulos([3, 12, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], 12) > 0.9  # ruido de una introducción
    assert puntaje_capitulos(list(range(1, 19)) * 12, 12) == 0.0  # versículos, no capítulos
    assert calidad_versos([1, 2, 3, 4, 1, 2, 3, 1, 2, 3, 4, 5]) == 1.0
    assert calidad_versos([7, 3, 9, 1, 12, 4]) < 0.5


def test_margenes_de_la_css():
    clases = margenes_superiores([CSS, "@media screen { .estrofa { margin: 1em 0 0 0 } } .nada { margin-top: 0 }"])
    assert clases == {"top05": 0.5, "top1": 1.0, "estrofa": 1.0}


def test_inspeccion_enfocada_sugiere_y_prueba(proyecto_bj):
    inf = inspeccionar(proyecto_bj, None, "qo")
    assert inf.mejora
    assert inf.cambios == {
        "capitulo": f"b, {CAPITULO_DEFECTO}",
        "bloque_corto_chars": 100,
        "estrofa": ".top05",
    }
    assert "Con la sugerencia:    12/12 capítulos" in inf.texto
    assert "Configuración actual: 1/12 capítulos" in inf.texto
    assert "bja inspeccionar --libro qo --aplicar" in inf.texto
    assert "/ ¡humo y más humo, todo es humo!" in inf.texto  # vista previa canónica
    assert "## Esqueleto" in inf.texto


def test_inspeccion_de_un_documento(proyecto_bj):
    inf = inspeccionar(proyecto_bj, None, None, "4")
    assert "part0004.xhtml" in inf.texto and "## Esqueleto" in inf.texto and not inf.cambios


# ------------------------------------------------------------------ edición de config.toml
def test_actualizar_config_conserva_comentarios_y_hace_copia(proyecto_bj):
    ruta = proyecto_bj.ruta_config
    respaldo = actualizar_config(ruta, "epub", {"bloque_corto_chars": 100, "estrofa": ".top05"})
    texto = ruta.read_text(encoding="utf-8")
    assert "# mi configuración" in texto and respaldo.exists()
    assert 'archivo = "libros/biblia.epub"\nbloque_corto_chars = 100\nestrofa = ".top05"\n' in texto
    actualizar_config(ruta, "deepgram", {"voz": "aura-2-luciano-es"})
    texto = ruta.read_text(encoding="utf-8")
    assert 'voz = "aura-2-luciano-es"\n' in texto and "# España" not in texto
    cfg = cargar_config(ruta)
    assert cfg.epub.bloque_corto_chars == 100 and cfg.deepgram.voz == "aura-2-luciano-es"


def test_actualizar_config_rechaza_un_resultado_invalido(proyecto_bj):
    ruta = proyecto_bj.ruta_config
    antes = ruta.read_text(encoding="utf-8")
    with pytest.raises(ConfigError, match="clave_que_no_existe"):
        actualizar_config(ruta, "epub", {"clave_que_no_existe": 1})
    assert ruta.read_text(encoding="utf-8") == antes


# ------------------------------------------------------------------ CLI
runner = CliRunner()


def _cli(cfg: Config, *args, codigo: int = 0) -> str:
    r = runner.invoke(app, ["--config", str(cfg.ruta_config), *args])
    assert r.exit_code == codigo, r.output
    return r.output


def test_flujo_de_un_libro_por_cli(proyecto_bj):
    salida = _cli(proyecto_bj, "correr", "qo", "1", codigo=1)
    assert "bja extraer --libro qo" in salida  # guía en vez de "se salta"
    salida = _cli(proyecto_bj, "inspeccionar", "--libro", "qo", "--aplicar")
    assert "config.toml actualizado" in salida
    assert cargar_config(proyecto_bj.ruta_config).epub.bloque_corto_chars == 100
    salida = _cli(proyecto_bj, "extraer", "--libro", "qo")
    assert "12/12" in salida
    assert (proyecto_bj.dir_texto / "qo" / "012.txt").exists()
    salida = _cli(proyecto_bj, "correr", "qo", "1-2")
    assert (proyecto_bj.dir_salida / "simulado" / "25-qo" / "qo-002.mp3").exists()
    salida = _cli(proyecto_bj, "inspeccionar", "--libro", "qo", "--aplicar")
    assert "No hay nada que aplicar" in salida


def test_voces_usar_guarda_la_voz(proyecto_bj):
    salida = _cli(proyecto_bj, "voces", "--proveedor", "deepgram", "--usar", "aura-2-luciano-es")
    assert "aura-2-luciano-es" in salida
    assert cargar_config(proyecto_bj.ruta_config).deepgram.voz == "aura-2-luciano-es"
    salida = _cli(proyecto_bj, "voces", "--proveedor", "deepgram", "--usar", "javier")  # nombre corto
    assert "salida/deepgram-aura-2-javier-es/" in salida
    assert cargar_config(proyecto_bj.ruta_config).deepgram.voz == "aura-2-javier-es"
    salida = _cli(proyecto_bj, "voces", "--proveedor", "deepgram", "--usar", "lucianno", codigo=1)
    assert "no es una voz" in salida and "luciano" in salida


def test_correr_con_otra_voz_sin_tocar_la_configuracion(proyecto_bj):
    from bjaudio.proveedores import etiqueta_voz

    from bjaudio.texto import escribir_atomico

    escribir_atomico(proyecto_bj.dir_texto / "qo" / "001.txt", "# qo 1\n1 Palabras del predicador.\n2 Humo y más humo.\n")
    salida = _cli(proyecto_bj, "correr", "qo", "1", "--proveedor", "deepgram", "--simular",
                  "--voz", "javier", "--velocidad", "0.95")
    assert "deepgram-aura-2-javier-es-x0.95" in salida and "config.toml no cambia" in salida
    cfg = cargar_config(proyecto_bj.ruta_config)
    assert cfg.deepgram.voz == "aura-2-alvaro-es"
    assert etiqueta_voz(cfg, "deepgram") == "deepgram-aura-2-alvaro-es"  # a 1.0, la carpeta de siempre


def test_cfg_con_voz_valida_la_velocidad(proyecto_bj):
    from bjaudio.cli import cfg_con_voz
    from bjaudio.errores import ConfigError

    cfg = cfg_con_voz(proyecto_bj, "deepgram", "aura-2-luciano-es", 0.95)
    assert (cfg.deepgram.voz, cfg.deepgram.velocidad) == ("aura-2-luciano-es", 0.95)
    with pytest.raises(ConfigError):
        cfg_con_voz(proyecto_bj, "deepgram", None, 0.93)


# ------------------------------------------------------------------ otras estructuras
def _proyecto_con(tmp_path, documentos: dict[str, str]) -> Config:
    from .conftest import crear_epub

    (tmp_path / "libros").mkdir(exist_ok=True)
    crear_epub(tmp_path / "libros" / "biblia.epub", documentos)
    (tmp_path / "config.toml").write_text('proveedor = "simulado"\nasr = "simulado"\n', encoding="utf-8")
    return cargar_config(tmp_path / "config.toml")


def test_salmos_con_encabezados_y_la_configuracion_por_defecto(tmp_path):
    from .conftest import xhtml

    salmos = "".join(
        f"<h3>SALMO {n}{f' ({n - 1})' if n > 9 else ''}</h3>"
        + "".join(f"<p><sup>{v}</sup>Verso {v} del salmo, con su texto.</p>" for v in range(1, 6))
        for n in range(1, 151)
    )
    cfg = _proyecto_con(tmp_path, {"sal.xhtml": xhtml(f"<h1>LOS SALMOS</h1>{salmos}")})
    inf = inspeccionar(cfg, None, "sal")
    assert "Configuración actual: 150/150 capítulos" in inf.texto
    assert "capitulo" not in inf.cambios  # los encabezados ya los atrapa el selector por defecto


def test_capitulos_en_span_y_versiculos_mixtos_sup_y_enlace(tmp_path):
    from .conftest import xhtml

    def capitulo(c: int) -> str:
        versos = []
        for v in range(1, 9):
            numero = f'<a href="m.xhtml#{c}_{v}">{v}</a>' if v % 3 == 0 else f"<sup>{v}</sup>"
            versos.append(f"{numero}Texto del versículo con varias palabras para que sea prosa normal. ")
        return f'<p><span class="num">{c}</span>{"".join(versos)}</p>'

    cuerpo = "<h1>RUT</h1>" + "".join(capitulo(c) for c in range(1, 5))
    cfg = _proyecto_con(tmp_path, {"rt.xhtml": xhtml(cuerpo)})
    inf = inspeccionar(cfg, None, "rt")
    assert inf.cambios["capitulo"].startswith("span.num, ")
    assert inf.cambios["versiculo"].startswith("sup, a, ") or inf.cambios["versiculo"].startswith("a, ")
    assert "Con la sugerencia:    4/4 capítulos · 32 versículos" in inf.texto
