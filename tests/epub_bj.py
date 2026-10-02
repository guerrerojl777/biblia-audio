"""EPUB sintético con la estructura típica de una Biblia de Jerusalén convertida con Sigil.

Texto inventado. Reproduce los rasgos que importan para el extractor:
- capítulos marcados con <b>N</b> al comienzo del párrafo (el 1 sin marca),
- versículos en <sup>N</sup>, llamadas de nota <a href=…>*</a>,
- poesía con un <p> por línea (clases sup1/l2) y estrofas con .top05 (margen en la CSS),
- una introducción con el mismo título del libro y referencias en negrita,
- notas y notas marginales en documentos aparte, con títulos «Notas | …»,
- un título de libro numerado sin ordinal («SAMUEL») y un libro de un solo capítulo.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from .conftest import CONTAINER, xhtml

CSS = """
p { margin: 0; text-indent: 1.2em; }
p.noindent { text-indent: 0; }
.top05 { margin-top: 0.5em; }
.top1 { margin-top: 1em; }
p.l2 { margin-left: 2em; text-indent: 0; }
.sup1 { text-indent: -0.6em; }
h4 { margin-top: 1.2em; }
"""


def _nota(n: int) -> str:
    return f'<a href="part0007.xhtml#n{n}">*</a>'


def _prosa(cap: int) -> str:
    return (
        f'<p><b>{cap}</b><sup>1</sup>Al empezar este capítulo el sabio observó la plaza{_nota(cap)} y anotó lo que vio. '
        f"<sup>2</sup>Las personas iban y venían con prisa, cada una ocupada en su propio asunto sin mirar a las demás. "
        f"<sup>3</sup>Entonces escribió que nada de eso dejaba huella, y que el viento se llevaba las palabras.</p>"
    )


def documentos_bj() -> dict[str, str]:
    capitulos_qo = "".join(_prosa(c) for c in range(4, 12))
    return {
        "part0000.xhtml": xhtml('<h1>«BIBLIA DE JERUSALÉN»</h1><p>Índice general <b>4</b> y <b>9</b>.</p>'),
        "part0001.xhtml": xhtml('<h1 class="master">LOS LIBROS SAPIENCIALES</h1>'),
        "part0002.xhtml": xhtml(
            "<h1>ECLESIASTÉS</h1>"
            "<p>Introducción del editor. El poema del tiempo (<b>3</b> 1-8) y el final (<b>12</b> 1-7) "
            "son los pasajes más citados.<sup>1</sup></p>"
        ),
        "part0003.xhtml": xhtml(
            "<h1>ECLESIASTÉS</h1>"
            "<h4>Título</h4>"
            f'<p class="noindent"><sup>1</sup>Palabras del predicador, hijo del rey.{_nota(1)}</p>'
            "<h4>Prólogo</h4>"
            '<p class="sup1 top05"><sup>2</sup>¡Humo y más humo!, dice el predicador,</p>'
            '<p class="l2">¡humo y más humo, todo es humo!</p>'
            '<p class="sup1"><sup>3</sup>¿Qué gana la gente</p>'
            '<p class="l2">con todo el trabajo que hace?</p>'
            '<p class="sup1 top05"><sup>4</sup>Una generación se va,</p>'
            '<p class="l2">otra generación viene.</p>'
            f'<p><b>2</b><sup>1</sup>Dije en mi corazón que probaría la alegría y gozaría del bien{_nota(2)}. '
            "<sup>2</sup>Pero también esto era humo, y de la risa dije que era locura, y del placer, ¿de qué sirve? "
            "<sup>3</sup>Este párrafo es largo a propósito para que cuente como prosa y no como línea poética.</p>"
            "<h4>El tiempo</h4>"
            '<p class="sup1"><b>3</b><sup>1</sup>Todo tiene su momento,</p>'
            '<p class="l2">cada cosa su tiempo bajo el cielo:</p>'
            '<p class="sup1 top05"><sup>2</sup>tiempo de sembrar,</p>'
            '<p class="l2">tiempo de cosechar.</p>'
            f"{capitulos_qo}"
            '<p><b>12</b><sup>1</sup>Acuérdate del creador en los días de la juventud, antes de que lleguen los días malos. '
            "<sup>2</sup>Antes de que se oscurezca el sol y la luna y las estrellas. <sup>3</sup>Fin del libro.</p>"
        ),
        "part0004.xhtml": xhtml(
            "<h1>SAMUEL</h1>"
            "<p><b>1</b><sup>1</sup>Había un hombre de la montaña. <sup>2</sup>Tenía dos mujeres.</p>"
            "<p><b>2</b><sup>1</sup>Entonces ella cantó. <sup>2</sup>Y se fue a su casa.</p>"
        ),
        "part0005.xhtml": xhtml(
            "<h1>EPÍSTOLA A FILEMÓN</h1>"
            "<p><sup>1</sup>Pablo, prisionero, al querido amigo. <sup>2</sup>A la hermana y a la comunidad.</p>"
        ),
        "part0006.xhtml": xhtml('<h1 class="master">APÉNDICES</h1>'),
        "part0007.xhtml": xhtml(
            "<h1>Notas | Eclesiastés</h1>"
            '<p><span class="libro"><a href="part0003.xhtml#v1">1 1</a></span> Nota del editor <b>1</b> '
            "<sup>2</sup> que no debe leerse.</p>"
            '<p><span class="libro"><a href="part0003.xhtml#v2">3 1</a></span> Otra nota <b>3</b> <sup>4</sup>.</p>'
        ),
        "part0008.xhtml": xhtml(
            "<h1>Notas marginales | Eclesiastés</h1>"
            '<p class="lead"><a href="part0003.xhtml#m1"><b>1</b></a> Gn 1 1</p>'
        ),
    }


def crear_epub_bj(ruta: Path) -> Path:
    docs = documentos_bj()
    items = "\n".join(
        f'<item id="d{i}" href="Text/{n}" media-type="application/xhtml+xml"/>' for i, n in enumerate(docs)
    )
    spine = "\n".join(f'<itemref idref="d{i}"/>' for i in range(len(docs)))
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Prueba BJ</dc:title></metadata>
  <manifest>{items}
    <item id="css" href="Styles/estilo.css" media-type="text/css"/>
  </manifest>
  <spine>{spine}</spine>
</package>"""
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/Styles/estilo.css", CSS)
        for nombre, contenido in docs.items():
            z.writestr(f"OEBPS/Text/{nombre}", contenido)
    return ruta
