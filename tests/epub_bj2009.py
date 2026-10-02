"""EPUB sintético con la estructura de la BJ 2009 convertida con Sigil (la del EPUB real).

Texto inventado. Reproduce los rasgos que importan para el extractor y el inspector:
- capítulos marcados con abreviatura + número en <span class="capital">Ag 1</span> al
  comienzo del párrafo; en los libros poéticos, <span class="salmocapital">;
- salmos con encabezados <h3>SALMO N (N)</h3>, uno doble («SALMO 2-3») cuyo segundo salmo
  empieza en un <span class="salmocapital">Sal 3</span>, y un índice interno con «SALMO N»;
- versículos en <sup>N</sup> (a veces dentro de un <a>), con letras («1a»), unidos («2-3»),
  entre corchetes sin texto («[4]», «[5] 6») y llamadas de nota <a>*</a>;
- versículos traspuestos: marcas Na 1, Na 2, Na 1, Na 2 con versículos distintos;
- texto entre la marca de capítulo y el versículo 1; aclamación sin número antes del 1;
- un prólogo con versículos propios antes del capítulo 1 sin marca (Eclesiástico);
- poesía con un <p> por línea y estrofas con .top05; rótulos <p class="flm"> (quién habla,
  letras de un acróstico), uno en versalitas; un número romano solo en un párrafo;
- cantidades con separador de miles; un título con llamada de nota antes del punto;
- índice interno de cada libro (h2 «Índice» + p.l1 > a), que en Joel repite las marcas de
  capítulo («CAPÍTULO 1»…) como en el índice de los Salmos, y notas en un documento aparte.
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
p.l1 { margin-left: 1em; }
p.l2 { margin-left: 2em; text-indent: 0; }
.sup1, .sup2 { text-indent: -0.6em; }
p.flm { font-variant: small-caps; }
p.centro { text-align: center; }
h4 { margin-top: 1.2em; }
"""


def _nota(n: int) -> str:
    return f'<a href="part0010.xhtml#n{n}">*</a>'


def _indice(*entradas: str) -> str:
    lineas = "".join(f'<p class="l1"><a href="#s{i}">{e}</a></p>' for i, e in enumerate(entradas))
    return f'<h2>Índice</h2>{lineas}<div class="pba"></div>'


def documentos_bj2009() -> dict[str, str]:
    return {
        "part0000.xhtml": xhtml("<h1>«BIBLIA DE PRUEBA»</h1><p>Presentación de la edición.</p>"),
        "part0001.xhtml": xhtml(
            "<h1>AGEO</h1><p>Introducción del editor: el libro tiene dos partes.<sup>1</sup> "
            "Se escribió después del regreso.</p>"
        ),
        "part0002.xhtml": xhtml(
            "<h1>AGEO</h1>" + _indice("Primera parte", "Segunda parte") + "<h1>AGEO</h1>"
            f'<p class="noindent"><span class="capital">Ag 1</span><sup>1</sup>El año primero del rey de la '
            f"ciudad llegó un mensaje al gobernador.{_nota(1)} <a href=\"#v2\"><sup>2</sup></a>Así habla el "
            "mensajero: este pueblo dice que aún no es tiempo.</p>"
            f"<h4>El templo{_nota(2)}.</h4>"
            "<p><sup>3</sup>Entonces habló otra vez el mensajero a todo el pueblo reunido en la plaza mayor. "
            "<sup>4</sup>¿Es tiempo de vivir en casas techadas mientras la casa común sigue en ruinas? "
            "<sup>5</sup>Los hijos de Parós eran 2.172; los hijos de Ará, 775.</p>"
            '<p class="centro">II</p>'
            "<p><sup>6</sup>Sembrasteis mucho y cosechasteis poco, comisteis sin saciaros y bebisteis sin "
            "alegraros, os vestisteis sin abrigaros.</p>"
            '<p class="noindent"><span class="capital">Ag 2</span>El día veinticuatro del mes sexto. '
            "<sup>1</sup>El día veintiuno del mes séptimo llegó otro mensaje para el gobernador de la ciudad. "
            "<sup>2</sup>Habla ahora al gobernador y al sacerdote mayor. <sup>3</sup>¿Quién de vosotros vio "
            "esta casa en su primer esplendor?</p>"
        ),
        "part0003.xhtml": xhtml(
            "<h1>NAHÚM</h1>"
            '<p class="noindent"><span class="capital">Na 1</span><sup>1</sup>Oráculo sobre la ciudad grande. '
            "<sup>2</sup>Un juez celoso es el señor del monte. <sup>3</sup>Lento a la ira y grande en poder.</p>"
            "<h4>El asedio</h4>"
            '<p class="noindent"><span class="capital">Na 2</span><sup>3</sup>Porque el señor restaura la viña '
            "arrasada. <sup>4</sup>Los escudos de sus valientes son rojos.</p>"
            '<p class="noindent"><span class="capital">Na 1</span><sup>4</sup>Increpa al mar y lo seca.</p>'
            '<p class="noindent"><span class="capital">Na 2</span><sup>1</sup>Mirad sobre los montes los pies '
            "del mensajero. <sup>2</sup>Sube el destructor contra ti. <sup>5</sup>Por las calles corren los "
            "carros enloquecidos.</p>"
            '<p class="noindent"><span class="capital">Na 3</span><sup>1</sup>¡Ay de la ciudad que no descansa! '
            "<sup>2</sup>Chasquido de látigo, estrépito de ruedas.</p>"
        ),
        "part0004.xhtml": xhtml(
            "<h1>SOFONÍAS</h1>"
            '<p class="noindent"><span class="capital">So 1</span><sup>1a</sup>Sueño del vigía en la torre. '
            "<sup>1b</sup>Vio dos dragones que luchaban. <sup>1c</sup>Y despertó temblando.</p>"
            '<p class="noindent"><span class="capital">So 1</span><sup>1</sup>Palabra que llegó al vigía. '
            "<sup>2</sup>Barreré todo de la faz de la tierra. <sup>3</sup>Barreré hombres y bestias.</p>"
            '<p class="noindent"><span class="capital">So 2</span><sup>1</sup>Congregaos, gente sin vergüenza. '
            "<sup>2 – 3</sup>Antes de que seáis como paja que se lleva el viento, buscad la justicia."
            "<sup>[4]</sup> <sup>[5] 6</sup>La costa quedará abandonada. <sup>7ab</sup>Será para el resto de "
            "la casa.</p>"
            '<p class="noindent"><span class="capital">So 3</span><sup>1</sup>¡Ay de la ciudad rebelde! '
            "<sup>2</sup>No escuchó la voz.</p>"
        ),
        "part0005.xhtml": xhtml(
            "<h1>LOS SALMOS</h1>" + _indice("SALMO 1", "SALMO 2-3", "SALMO 4") + "<h1>LOS SALMOS</h1>"
            "<h3>SALMO 1 (1)</h3>"
            f"<h5>Los dos caminos{_nota(3)}</h5>"
            '<p class="sup1 top05"><sup>1</sup>Dichoso el que camina recto,</p>'
            '<p class="l2">el que no se sienta con los burlones,</p>'
            '<p class="sup1"><sup>2</sup>sino que medita de día y de noche.</p>'
            "<h3>SALMO 2-3 (2-3)</h3>"
            '<p class="cero"><sup>1</sup>Canción del caminante.</p>'
            '<p class="sup1 top05"><sup>2</sup>¿Por qué se agitan las naciones,</p>'
            '<p class="l2">por qué planean cosas vanas?</p>'
            '<p class="cap noindent"><span class="salmocapital">Sal 3</span><sup>1</sup>Señor, cuántos son '
            "los que me rodean,</p>"
            '<p class="l2">cuántos se levantan contra mí.</p>'
            f"<h3>SALMO 4 {_nota(4)}</h3>"
            '<p class="cero">¡Aleluya!</p>'
            '<p class="sup1 top05"><sup>1</sup>Cuando grito, respóndeme,</p>'
            '<p class="l2">tú que me haces justicia.</p>'
            '<p class="flm">Álef.</p>'
            '<p class="sup2 top05"><sup>2</sup>Dichosos los de camino intachable,</p>'
            '<p class="l2">los que siguen la enseñanza.</p>'
            '<p class="flm">Bet.</p>'
            '<p class="sup2 top05"><sup>3</sup>Con todo el corazón te busco,</p>'
            '<p class="l2">no me dejes desviar.</p>'
        ),
        "part0006.xhtml": xhtml(
            "<h1>ECLESIÁSTICO</h1><h4>Prólogo</h4><p>"
            + " ".join(f"<sup>{i}</sup>Frase {i} del traductor sobre la obra de su abuelo." for i in range(1, 13))
            + "</p><h2>Primera parte</h2>"
            '<p class="noindent"><span class="capital">Si 1</span><sup>1</sup>Toda sabiduría viene de lo alto. '
            "<sup>2</sup>La arena del mar, ¿quién la contará? <sup>3</sup>La altura del cielo, ¿quién la medirá?</p>"
            '<p class="noindent"><span class="capital">Si 2</span><sup>1</sup>Hijo, si te acercas a servir, '
            "prepárate. <sup>2</sup>Endereza tu corazón y sé constante.</p>"
        ),
        "part0007.xhtml": xhtml(
            "<h1>CANTAR DE LOS CANTARES</h1><h2>Primer canto</h2>"
            '<p class="cap noindent"><span class="salmocapital">Ct 1</span><sup>1</sup>Canto de los cantos, '
            "del joven rey.</p>"
            '<p class="flm">L<span class="versalita">A AMADA</span>.</p>'
            '<p class="sup1 top05"><sup>2</sup>Que me hable con palabras de su boca,</p>'
            '<p class="l2">mejores que el vino son tus palabras.</p>'
            '<h4>E<span class="versalita">L CORO</span></h4>'
            '<p class="sup1 top05"><sup>3</sup>Buscaremos tu nombre,</p>'
            '<p class="l2">lo diremos en la plaza.</p>'
        ),
        "part0008.xhtml": xhtml(
            "<h1>ABDÍAS</h1>"
            '<p class="sup1 top05"><sup>1</sup>Visión del vigía.</p>'
            '<p class="l2">Esto dice el mensajero:</p>'
            '<p class="sup1"><sup>2</sup>Te haré pequeño entre las naciones.</p>'
        ),
        "part0011.xhtml": xhtml(
            "<h1>JOEL</h1>" + _indice("CAPÍTULO 1", "CAPÍTULO 2-3", "CAPÍTULO 4") + "<h1>JOEL</h1>"
            "<h3>CAPÍTULO 1</h3><p><sup>1</sup>Palabra que llegó al hijo del vigía. <sup>2</sup>Oíd esto, ancianos.</p>"
            "<h3>CAPÍTULO 2-3</h3><p><sup>1</sup>Tocad la trompeta en el monte. <sup>2</sup>Día de nubes y niebla.</p>"
            '<p class="cap noindent"><span class="salmocapital">Jl 3</span><sup>1</sup>Después de esto habrá '
            "sueños. <sup>2</sup>Hasta sobre los siervos y las siervas.</p>"
            "<h3>CAPÍTULO 4</h3><p><sup>1</sup>En aquellos días cambiará la suerte. <sup>2</sup>Se reunirán las "
            "naciones en el valle.</p>"
        ),
        "part0009.xhtml": xhtml('<h1 class="master">APÉNDICES</h1>'),
        "part0010.xhtml": xhtml(
            "<h1>Notas | Ageo</h1>"
            '<p><a href="part0002.xhtml#v1">1 1</a> Nota que no debe leerse <sup>2</sup>.</p>'
        ),
    }


def crear_epub_bj2009(ruta: Path) -> Path:
    docs = documentos_bj2009()
    items = "\n".join(
        f'<item id="d{i}" href="Text/{n}" media-type="application/xhtml+xml"/>' for i, n in enumerate(docs)
    )
    spine = "\n".join(f'<itemref idref="d{i}"/>' for i in range(len(docs)))
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Prueba BJ 2009</dc:title></metadata>
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
