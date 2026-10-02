"""Extracción, inspección y plan sobre un EPUB con la estructura de la BJ 2009 (texto inventado).

Cada prueba reproduce un rasgo que apareció en el EPUB real y que la versión 0.2 no
resolvía: marcas de capítulo con abreviatura, traspuestos, versículos con letras, unidos o
entre corchetes, prólogo con versículos propios, salmos con encabezado doble, rótulos…
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from bjaudio.asr import SimuladoASR
from bjaudio.config import CAPITULO_REGEX_DEFECTO, Config, ConfigEpub, cargar_config
from bjaudio.epub import Epub
from bjaudio.errores import BjaError
from bjaudio.extraccion import compactar, diagnosticar, extraer, extraer_a_disco, informe
from bjaudio.inspeccion import inspeccionar
from bjaudio.lexico import Entrada, Lexico
from bjaudio.libros import obtener
from bjaudio.normalizar import numeros_a_palabras, tokenizar
from bjaudio.pipeline import Pipeline
from bjaudio.plan import planificar, suavizar_mayusculas
from bjaudio.proveedores.simulado import SimuladoTTS
from bjaudio.texto import LINEA, PARRAFO, Capitulo, Unidad, escribir_atomico, parsear

from .conftest import crear_epub, xhtml
from .epub_bj2009 import crear_epub_bj2009

# Lo que se recomienda para el EPUB real (el resto, por defecto).
RECOMENDADA = ConfigEpub(bloque_corto_chars=100, estrofa=".top05, .top1", rotulo=".flm")
REGEX_V02 = r"^\s*(?:(?:cap[ií]tulo|salmo)\s+)?(\d{1,3})\s*$|^\s*(?:cap[ií]tulo|salmo)\s+(\d{1,3})\b"


@pytest.fixture
def epub_2009(tmp_path) -> Path:
    (tmp_path / "libros").mkdir()
    return crear_epub_bj2009(tmp_path / "libros" / "biblia.epub")


@pytest.fixture
def res(epub_2009):
    return _extraer(epub_2009)


def _extraer(ruta: Path, cfg: ConfigEpub = RECOMENDADA, libro: str | None = None):
    with Epub(ruta) as e:
        return extraer(e, cfg, libro)


def _caps(res, libro: str) -> dict[int, Capitulo]:
    return {c.numero: c for c in res.capitulos if c.libro == libro}


def _proyecto(tmp_path: Path, epub_extra: str = "") -> Config:
    (tmp_path / "config.toml").write_text(
        'proveedor = "simulado"\nasr = "simulado"\n\n[epub]\narchivo = "libros/biblia.epub"\n' + epub_extra,
        encoding="utf-8",
    )
    return cargar_config(tmp_path / "config.toml")


# ------------------------------------------------------------------ capítulos
def test_capitulos_con_abreviatura_sin_configurar_nada(epub_2009):
    res = _extraer(epub_2009, ConfigEpub())
    assert sorted(_caps(res, "ag")) == [1, 2]
    assert sorted(_caps(res, "na")) == [1, 2, 3]
    assert sorted(_caps(res, "so")) == [1, 2, 3]
    assert sorted(_caps(res, "jl")) == [1, 2, 3, 4]
    assert sorted(_caps(res, "abd")) == [1]
    todo = " ".join(u.texto for c in res.capitulos for u in c.unidades)
    for ajeno in ("Ag 1", "Na 2", "Sal 3", "Introducción", "no debe leerse", "Índice", "*"):
        assert ajeno not in todo
    assert not any("número suelto" in a for a in res.avisos)


def test_traspuestos_se_unen_en_el_orden_del_libro(res):
    na = _caps(res, "na")
    assert na[1].versiculos == ["1", "2", "3", "4"]
    assert na[2].versiculos == ["3", "4", "1", "2", "5"]
    assert na[2].fragmentos == [["3", "4"], ["1", "2", "5"]]
    assert [s.titulo for s in na[2].secciones] == ["El asedio"]
    segundo = na[2].unidades[2]
    assert segundo.versiculo == "1" and segundo.ruptura >= PARRAFO  # pausa larga entre trozos
    nota = next(n for n in res.notas if n.startswith("na 2 —"))
    assert "3–4 | 1–2, 5" in nota and "traspuestos" in nota
    assert not any(a.startswith("na") for a in res.avisos)  # nada que revisar: no cambia lo que se oye
    assert not any(n.startswith("na 2") and "cambio(s) de orden" in n for n in res.notas)


def test_versiculos_con_letras_unidos_y_entre_corchetes(res):
    so = _caps(res, "so")
    assert so[1].versiculos == ["1a", "1b", "1c", "1", "2", "3"]  # dos trozos «So 1» unidos
    dos = so[2]
    assert dos.versiculos == ["1", "2-3", "6", "7ab"]
    assert [o.versiculo for o in dos.omitidos] == ["4", "5"]
    texto = dos.a_texto()
    assert "\n2-3 Antes de" in texto and "\n% [4] " in texto and "\n% [5] " in texto and "\n7ab Será" in texto
    assert parsear(texto).versiculos == dos.versiculos  # el formato canónico se relee igual
    assert not any(a.startswith("so 2") for a in res.avisos)  # ni «faltan 4, 5» ni otra cosa
    assert any(n.startswith("so 2") and "4, 5" in n for n in res.notas)


def test_texto_antes_del_versiculo_1_es_el_0(res):
    assert _caps(res, "ag")[2].versiculos[:2] == ["0", "1"]
    assert _caps(res, "sal")[4].versiculos == ["0", "1", "2", "3"]  # aclamación sin número
    assert not any("repetidos" in a for a in res.avisos)


def test_prologo_con_versiculos_propios_es_el_capitulo_0(res):
    si = _caps(res, "si")
    assert sorted(si) == [0, 1, 2]
    assert si[0].versiculos == [str(i) for i in range(1, 13)]
    assert [s.titulo for s in si[0].secciones] == ["Prólogo"]
    assert si[1].versiculos == ["1", "2", "3"] and [s.titulo for s in si[1].secciones] == ["Primera parte"]
    assert any(n.startswith("si 0") and "prólogo" in n for n in res.notas)
    assert not any(a.startswith("si 1") for a in res.avisos)
    assert obtener("si").anuncio(0) == "Eclesiástico. Prólogo."
    assert "si       2/51   capítulos" in informe(res) and "+ prólogo" in informe(res)


def test_numero_suelto_en_una_introduccion_no_crea_capitulo(res):
    # La introducción de Ageo tiene un <sup>1</sup> con texto detrás: se asume un capítulo 1
    # sin marca, que pierde contra el «Ag 1» real.
    ag = _caps(res, "ag")
    assert "Introducción" not in " ".join(u.texto for u in ag[1].unidades)
    assert any(n.startswith("ag 1 — descarto un trozo sin marca") for n in res.notas)


# ------------------------------------------------------------------ salmos y poesía
def test_salmos_con_encabezado_doble_y_rotulos(res):
    sal = _caps(res, "sal")
    assert sorted(sal) == [1, 2, 3, 4]
    assert sal[1].secciones[0].titulo == "Los dos caminos"
    assert sal[1].unidades[1].ruptura == LINEA
    assert sal[2].versiculos == ["1", "2"] and sal[3].versiculos == ["1"]
    textos = [u.texto for u in sal[4].unidades]
    i = textos.index("Álef.")
    assert sal[4].unidades[i].ruptura == PARRAFO and sal[4].unidades[i + 1].ruptura >= PARRAFO


def test_capitulos_por_encabezado_doble_fuera_de_salmos(res):
    jl = _caps(res, "jl")
    assert [jl[n].versiculos for n in (1, 2, 3, 4)] == [["1", "2"]] * 4


def test_titulos_y_rotulos_en_versalitas(res, tmp_path):
    ct = _caps(res, "ct")[1]
    assert "LA AMADA." in [u.texto for u in ct.unidades]
    assert [s.titulo for s in ct.secciones] == ["Primer canto", "EL CORO"]  # sin «E L CORO»
    trozos = planificar(ct, obtener("ct"), Config(raiz=tmp_path), Lexico(), 2000)
    assert any("La Amada." in t.texto for t in trozos)


def test_romano_solo_es_titulo_y_el_punto_va_pegado(res):
    ag = _caps(res, "ag")[1]
    assert [s.titulo for s in ag.secciones] == ["El templo.", "II"]
    assert "II" not in [u.texto for u in ag.unidades]
    assert any(n.startswith("ag —") and "cifras" in n for n in res.notas)


# ------------------------------------------------------------------ inspector
def test_inspector_reconoce_marcas_con_abreviatura(epub_2009, tmp_path):
    inf = inspeccionar(_proyecto(tmp_path), libro="na")
    assert "Configuración actual: 3/3 capítulos" in inf.texto
    assert "«span.capital» (p. ej. «Na 1»)" in inf.texto and "ya los reconoce" in inf.texto


def test_inspector_corrige_la_regex_de_la_02(epub_2009, tmp_path):
    cfg = _proyecto(tmp_path, f"capitulo_regex = '{REGEX_V02}'\n")
    inf = inspeccionar(cfg, libro="na")
    assert "Configuración actual: 1/3 capítulos" in inf.texto
    assert inf.mejora and inf.cambios["capitulo_regex"] == CAPITULO_REGEX_DEFECTO
    assert "Con la sugerencia:    3/3 capítulos" in inf.texto


def test_inspector_prefiere_marcas_seguidas_de_versiculos_al_indice(epub_2009, tmp_path):
    inf = inspeccionar(_proyecto(tmp_path), libro="jl")
    deduje = inf.texto.split("## Lo que deduje", 1)[1].split("\n## ", 1)[0]
    assert "capítulos: «h3»" in deduje and "«span.salmocapital» (3)" in deduje
    assert "p.l1" not in deduje
    assert "Configuración actual: 4/4 capítulos" in inf.texto


def test_inspector_sugiere_solo_pausas_si_ya_extrae_bien(epub_2009, tmp_path):
    inf = inspeccionar(_proyecto(tmp_path), libro="sal")
    assert inf.mejora and set(inf.cambios) <= {"bloque_corto_chars", "estrofa"}
    assert "mejora las pausas" in inf.texto


# ------------------------------------------------------------------ texto, plan y audio
def test_formato_canonico_acepta_las_etiquetas_nuevas():
    cap = parsear("# dn 3\n0 Antes.\n1 Uno.\n24-25 Unidos.\n40ab Dos letras.\n% [26] comentario\n\n24 Otra vez.\n")
    assert cap.versiculos == ["0", "1", "24-25", "40ab", "24"]


def test_cifras_a_palabras_y_tokens_iguales():
    assert numeros_a_palabras("Parós: 2.172; Ará, 775.") == "Parós: dos mil ciento setenta y dos; Ará, setecientos setenta y cinco."
    assert numeros_a_palabras("un total de 1.100.000") == "un total de un millón cien mil"
    assert numeros_a_palabras("el 2.º día y la 1.ª carta") == "el segundo día y la primera carta"
    assert numeros_a_palabras("v. 4b y 3,5") == "v. 4b y 3,5"
    # El reconocedor puede escribir la cifra con punto o coma: se compara igual.
    assert tokenizar("eran 46.500") == tokenizar("eran 46,500") == tokenizar("eran cuarenta y seis mil quinientos")


def test_mayusculas_suavizadas_para_la_voz():
    assert suavizar_mayusculas("LA AMADA. Dijo el SEÑOR a Antíoco IV") == "La Amada. Dijo el Señor a Antíoco IV"


def test_compactar_rangos():
    assert compactar(["7", "8", "2", "3", "4"]) == "7–8, 2–4"
    assert compactar(["1a", "1b", "1c", "1", "2"]) == "1a–1c, 1–2"


def test_numero_suelto_avisa_solo_si_parece_una_marca():
    def cap(*textos: str) -> Capitulo:
        return Capitulo("ne", 7, [Unidad(str(i + 1), t, 0, True) for i, t in enumerate(textos)])

    assert not any("número suelto" in a for a in diagnosticar([cap("Los de Parós: 2.172; los de Ará: 775.")]))
    assert any("número suelto" in a for a in diagnosticar([cap("Así fue. 5 Entonces se fueron.")]))
    assert any("número suelto" in a for a in diagnosticar([cap("Uno.", "Qo 2")]))


def test_tiempos_de_versiculos_numerados_dos_veces(proyecto):
    texto = "# dn 3\n" + "".join(f"{v} Frase del versículo {v} con algo de texto.\n" for v in range(22, 26))
    texto += "\n" + "".join(f"{v} Otra frase con el mismo número {v} y más texto.\n" for v in range(24, 27))
    escribir_atomico(proyecto.dir_texto / "dn" / "003.txt", texto)
    r = Pipeline(proyecto, SimuladoTTS(), SimuladoASR()).procesar("dn", 3)
    versos = json.loads(r.mp3.with_suffix(".json").read_text(encoding="utf-8"))["versiculos"]
    assert {"24", "25", "24#2", "25#2", "26"} <= set(versos)
    assert versos["24"] < versos["25"] < versos["24#2"] < versos["25#2"] < versos["26"]


def test_extraer_a_disco_escribe_el_prologo(epub_2009, tmp_path):
    cfg = _proyecto(tmp_path)
    res, (nuevos, _iguales, _omitidos) = extraer_a_disco(cfg)
    assert (cfg.dir_texto / "si" / "000.txt").read_text(encoding="utf-8").startswith("# si 0\n")
    assert nuevos == len(res.capitulos)


def test_reextraer_pisa_lo_que_nadie_toco_y_respeta_lo_editado(epub_2009, tmp_path):
    cfg = _proyecto(tmp_path)
    extraer_a_disco(cfg, solo_libro="sal")
    tocado = cfg.dir_texto / "sal" / "001.txt"
    intacto = cfg.dir_texto / "sal" / "002.txt"
    tocado.write_text(tocado.read_text(encoding="utf-8") + "% una nota mía\n", encoding="utf-8")
    antes = intacto.read_text(encoding="utf-8")
    # Otra configuración (pausas de poesía): cambia el texto canónico de los salmos.
    cfg2 = replace(cfg, epub=replace(cfg.epub, bloque_corto_chars=100, estrofa=".top05"))
    _res, (nuevos, _iguales, omitidos) = extraer_a_disco(cfg2, solo_libro="sal")
    assert intacto.read_text(encoding="utf-8") != antes  # lo escribió la extracción: se actualiza
    assert omitidos == ["trabajo/texto/sal/001.txt"] and "% una nota mía" in tocado.read_text(encoding="utf-8")
    _res, (_n, _i, omitidos) = extraer_a_disco(cfg2, solo_libro="sal", forzar=True)
    assert omitidos == [] and "% una nota mía" not in tocado.read_text(encoding="utf-8")


def test_un_txt_viejo_sin_huella_no_se_pisa(epub_2009, tmp_path):
    cfg = _proyecto(tmp_path)
    viejo = "# na 1\n1 Todo el libro en un solo capítulo, como lo dejaba la 0.2.\n"
    escribir_atomico(cfg.dir_texto / "na" / "001.txt", viejo)
    _res, (_n, _i, omitidos) = extraer_a_disco(cfg, solo_libro="na")
    assert omitidos == ["trabajo/texto/na/001.txt"]
    assert (cfg.dir_texto / "na" / "001.txt").read_text(encoding="utf-8") == viejo


def test_correr_se_niega_con_un_capitulo_que_trae_varios(proyecto):
    texto = "# qo 1\n1 Uno.\n2 Dos.\n\n1 Otro uno.\n2 Otro dos.\n\n1 Y otro.\n"
    escribir_atomico(proyecto.dir_texto / "qo" / "001.txt", texto)
    with pytest.raises(BjaError, match="varios capítulos"):
        Pipeline(proyecto, SimuladoTTS(), SimuladoASR()).plan(obtener("qo"), 1)


# ------------------------------------------------------------------ casos límite (revisión de la 0.3)
def _epub_de(tmp_path: Path, cuerpo: str) -> Path:
    return crear_epub(tmp_path / "x.epub", {"p.xhtml": xhtml(cuerpo)})


def test_trozo_traspuesto_que_empieza_sin_numero_no_se_pierde(tmp_path):
    cuerpo = ('<h1>NAHÚM</h1>'
              '<p class="noindent"><span class="capital">Na 1</span><sup>1</sup>Oráculo. <sup>2</sup>Juez. <sup>3</sup>Lento a la ira</p>'
              '<p class="noindent"><span class="capital">Na 2</span><sup>3</sup>Restaura la viña. <sup>4</sup>Escudos.</p>'
              '<p class="noindent"><span class="capital">Na 1</span>y grande en poder. <sup>4</sup>Increpa al mar. <sup>5</sup>Tiembla.</p>'
              '<p class="noindent"><span class="capital">Na 2</span><sup>1</sup>Mirad. <sup>2</sup>Sube. <sup>5</sup>Carros.</p>')
    res = _extraer(_epub_de(tmp_path, cuerpo), ConfigEpub())
    uno = _caps(res, "na")[1]
    assert uno.versiculos == ["1", "2", "3", "4", "5"]
    continuacion = uno.unidades[3]  # el texto sin número sigue el versículo 3, tras una pausa larga
    assert continuacion.versiculo == "3" and not continuacion.inicia_versiculo and continuacion.ruptura >= PARRAFO
    assert any("(1–3 | 4–5)" in n for n in res.notas)


def test_capitulo_1_sin_marca_mas_un_traspuesto_marcado_no_es_prologo(tmp_path):
    cuerpo = ("<h1>ZACARÍAS</h1><p>" + " ".join(f"<sup>{i}</sup>Frase {i} del primer capítulo." for i in range(1, 13)) + "</p>"
              '<p class="noindent"><span class="capital">Za 2</span><sup>1</sup>Alcé los ojos. <sup>2</sup>Vi cuernos.</p>'
              '<p class="noindent"><span class="capital">Za 1</span><sup>13</sup>Respondió. <sup>14</sup>Clama.</p>')
    res = _extraer(_epub_de(tmp_path, cuerpo), ConfigEpub())
    za = _caps(res, "za")
    assert sorted(za) == [1, 2] and za[1].versiculos == [str(i) for i in range(1, 15)]


def test_introduccion_con_notas_numeradas_no_es_prologo(tmp_path):
    intro = "<h1>AMÓS</h1><h2>Introducción</h2><p>" + " ".join(
        f"Comentario del editor número {i} sobre el profeta.<sup>{i}</sup>" for i in range(1, 12)) + "</p>"
    texto = ('<p class="noindent"><span class="capital">Am 1</span><sup>1</sup>Palabras del pastor. '
             '<sup>2</sup>Dijo: el monte ruge.</p>')
    res = _extraer(_epub_de(tmp_path, intro + texto), ConfigEpub())
    am = _caps(res, "am")
    assert sorted(am) == [1] and "Comentario" not in " ".join(u.texto for u in am[1].unidades)
    assert any(a.startswith("am 1 — ¡OJO! descarto") for a in res.avisos)  # nunca en silencio


def test_titulo_de_libro_con_etiquetas_pegadas(tmp_path):
    cuerpo = ('<h1><span>CARTA A LOS</span><span>ROMANOS</span></h1>'
              '<p class="noindent"><span class="capital">Rm 1</span><sup>1</sup>Pablo, siervo. <sup>2</sup>Prometido antes.</p>')
    res = _extraer(_epub_de(tmp_path, cuerpo), ConfigEpub())
    assert sorted(_caps(res, "rm")) == [1]
    assert any(t.libro == "rm" and t.texto == "CARTA A LOS ROMANOS" for t in res.titulos)


def test_tiempos_repetidos_dentro_del_mismo_trozo(proyecto):
    texto = "# dn 3\n24 Primera frase.\n25 Segunda frase.\n24 Tercera frase.\n25 Cuarta frase.\n26 Quinta.\n"
    escribir_atomico(proyecto.dir_texto / "dn" / "003.txt", texto)
    r = Pipeline(proyecto, SimuladoTTS(), SimuladoASR()).procesar("dn", 3)
    versos = json.loads(r.mp3.with_suffix(".json").read_text(encoding="utf-8"))["versiculos"]
    assert list(versos) == ["24", "25", "24#2", "25#2", "26"]
    assert versos["24"] < versos["25"] < versos["24#2"] < versos["25#2"] < versos["26"]


def test_mayusculas_antes_del_lexico(tmp_path):
    cap = parsear("# qo 1\n1 Palabras de QOHÉLET.\n")
    lexico = Lexico({"Qohélet": Entrada("Qohélet", "Coélet", None)})
    trozos = planificar(cap, obtener("qo"), Config(raiz=tmp_path), lexico, 2000)
    assert "Coélet" in trozos[-1].texto


def test_numeros_concuerdan_con_el_sustantivo():
    assert numeros_a_palabras("21 hombres y 21 ovejas") == "veintiún hombres y veintiuna ovejas"
    assert numeros_a_palabras("675.000 ovejas, 72.000 bueyes") == "seiscientas setenta y cinco mil ovejas, setenta y dos mil bueyes"
    assert numeros_a_palabras("200 levitas y 1.254 túnicas") == "doscientos levitas y mil doscientas cincuenta y cuatro túnicas"
    assert numeros_a_palabras("21 de ellos; eran 200 para la guerra") == "veintiuno de ellos; eran doscientos para la guerra"
    assert numeros_a_palabras("el 3.º día, el 1.º de mayo, el 1.er año") == "el tercer día, el primero de mayo, el primer año"
    assert numeros_a_palabras("1 oveja y 1 hombre") == "una oveja y un hombre"
    assert numeros_a_palabras("Sal 119,105") == "Sal 119,105"  # la coma no es separador de miles en el texto


def test_huecos_de_numeracion_explican_si_el_texto_esta(tmp_path):
    from bjaudio.extraccion import observar

    def cap(versos: dict[str, str]) -> Capitulo:
        return Capitulo("jn", 5, [Unidad(v, t, 0, True) for v, t in versos.items()])

    normal = "Frase de largo normal para un versículo cualquiera del capítulo."
    versos = {str(n): normal for n in range(1, 14)}
    pegado = cap({**versos, "14": normal + " " + normal + " " + normal, "16": normal, "17": normal})
    nota = observar([pegado])[0]
    assert "falta el número del versículo 15" in nota and "al final del 14" in nota and "se lee igual" in nota
    ausente = cap({"1": normal, "2": normal, "3": normal, "4": normal, "6": normal, "7": normal})
    assert observar([ausente]) == ["jn 5 — esta edición no trae el versículo 5 (sus vecinos tienen el largo normal): se lee lo que hay"]
    tramo = cap({**{str(n): normal for n in range(1, 19)}, "28": normal, "29": normal})
    assert observar([tramo])[0].startswith("jn 5 — esta edición no trae los versículos 19–27")


def test_extraer_dice_si_no_hay_nada_que_revisar(epub_2009, tmp_path):
    from typer.testing import CliRunner

    from bjaudio.cli import app

    _proyecto(tmp_path)
    r = CliRunner().invoke(app, ["--config", str(tmp_path / "config.toml"), "extraer", "--libro", "na"])
    assert r.exit_code == 0, r.output
    assert "Nada que revisar antes de generar el audio" in r.output and "nota(s) informativa(s)" in r.output
