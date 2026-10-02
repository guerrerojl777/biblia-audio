"""Estructuras de EPUB menos amables: varios libros, poesía con <br/>, notas dentro del
capítulo, envoltorios por versículo, capítulos partidos entre archivos y entidades HTML."""

from __future__ import annotations

from bjaudio.config import ConfigEpub
from bjaudio.epub import Epub
from bjaudio.extraccion import extraer
from bjaudio.texto import LINEA, PARRAFO

from .conftest import crear_epub, xhtml

SALMOS = xhtml("""
<h1>LIBRO DE LOS SALMOS</h1>
<h2>Salmo 1</h2>
<p class="poema"><span class="verse"><span class="vn">1</span>Dichoso&nbsp;quien camina<br/>
por la senda recta,<br/>
y no se sienta en la plaza.</span></p>
<p class="poema"><span class="verse"><span class="vn">2</span>Su gusto está en la enseñanza.</span></p>
<aside epub:type="footnote"><p>1 a. Nota al pie que no debe leerse 1.</p></aside>
<h2>Salmo 2</h2>
<p class="poema"><span class="verse"><span class="vn">1</span>¿Por qué se agitan las ciu&#173;dades?</span></p>
""")

SAMUEL_A = xhtml("""
<h1>PRIMER LIBRO DE SAMUEL</h1>
<h2>1</h2>
<p><span class="verse"><span class="vn">1</span>Había un hombre de la montaña.</span>
<span class="verse"><span class="vn">2</span>Tenía dos mujeres.</span></p>
""")

SAMUEL_B = xhtml("""
<p><span class="verse"><span class="vn">3</span>Subía cada año al santuario.</span></p>
<h2>2</h2>
<p><span class="verse"><span class="vn">1</span>Entonces ella cantó.</span></p>
""")


def _cfg() -> ConfigEpub:
    return ConfigEpub(versiculo="span.vn", capitulo="h2", titulo_seccion="h3")


def test_varios_libros_poesia_y_capitulos_partidos(tmp_path):
    ruta = crear_epub(tmp_path / "b.epub", {"sal.xhtml": SALMOS, "1s-a.xhtml": SAMUEL_A, "1s-b.xhtml": SAMUEL_B})
    with Epub(ruta) as e:
        res = extraer(e, _cfg())
    assert [(c.libro, c.numero) for c in res.capitulos] == [("sal", 1), ("sal", 2), ("1s", 1), ("1s", 2)]
    sal1 = res.capitulos[0]
    assert [u.texto for u in sal1.unidades] == [
        "Dichoso quien camina", "por la senda recta,", "y no se sienta en la plaza.", "Su gusto está en la enseñanza.",
    ]
    assert [u.ruptura for u in sal1.unidades][1:] == [LINEA, LINEA, PARRAFO]
    todo = " ".join(u.texto for c in res.capitulos for u in c.unidades)
    assert "Nota al pie" not in todo
    assert res.capitulos[1].unidades[0].texto == "¿Por qué se agitan las ciudades?"  # guion suave fuera
    # el capítulo 1 de Samuel sigue en el segundo archivo
    assert res.capitulos[2].versiculos == ["1", "2", "3"]
    # solo los avisos esperables: el EPUB de prueba trae 2 salmos de 150 y 2 capítulos de 31
    assert all("capítulos; faltan" in a for a in res.avisos), res.avisos
