"""Utilidades de prueba: un proyecto temporal y un EPUB sintético (texto inventado)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from bjaudio.config import Config, cargar_config

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""


def _opf(nombres: list[str]) -> str:
    items = "\n".join(
        f'<item id="d{i}" href="{n}" media-type="application/xhtml+xml"/>' for i, n in enumerate(nombres)
    )
    spine = "\n".join(f'<itemref idref="d{i}"/>' for i in range(len(nombres)))
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Prueba</dc:title></metadata>
  <manifest>{items}
    <item id="fuente" href="fuentes/letra.otf" media-type="font/otf"/>
  </manifest>
  <spine>{spine}</spine>
</package>"""


def xhtml(cuerpo: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>x</title></head>
<body>{cuerpo}</body></html>"""


def crear_epub(ruta: Path, documentos: dict[str, str], extra: dict[str, str] | None = None) -> Path:
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", _opf(list(documentos)))
        z.writestr("OEBPS/fuentes/letra.otf", b"\x00fuente")
        for nombre, contenido in documentos.items():
            z.writestr(f"OEBPS/{nombre}", contenido)
        for nombre, contenido in (extra or {}).items():
            z.writestr(nombre, contenido)
    return ruta


GENESIS = xhtml("""
<h1 class="libro">GÉNESIS</h1>
<p class="intro">Introducción del editor que no debe leerse.</p>
<h2 class="capitulo">Capítulo 1</h2>
<h3 class="titulo">El comienzo</h3>
<p class="texto"><sup class="v">1</sup>Al principio la luz llenó la casa.<a class="nota" href="notas.xhtml#n1" epub:type="noteref"><sup>a</sup></a>
<sup class="v">2</sup>La mesa estaba servida, <a id="ancla"/>y el pan seguía tibio. <sup class="v">3</sup>Dijo el vecino: «Que haya fiesta».</p>
<p class="texto"><sup class="v">4</sup>Y hubo fiesta hasta la noche.</p>
<p class="poesia"><sup class="v">5</sup>Canta la tierra con su gente</p>
<p class="poesia">y el río responde al amanecer.</p>
<h2 class="capitulo">Capítulo 2</h2>
<p class="texto">Primer versículo sin número marcado. <sup class="v">2</sup>Segundo versículo.</p>
""")

NOTAS = xhtml("""
<h2>Notas</h2>
<p class="nota" id="n1">a. Esta nota del editor no debe colarse en el audio.</p>
""")


@pytest.fixture
def proyecto(tmp_path: Path) -> Config:
    (tmp_path / "libros").mkdir()
    crear_epub(tmp_path / "libros" / "biblia.epub", {"gn.xhtml": GENESIS, "notas.xhtml": NOTAS})
    (tmp_path / "config.toml").write_text(
        """
proveedor = "simulado"
asr = "simulado"
edicion = "Edición de prueba"

[epub]
archivo = "libros/biblia.epub"
linea_poetica = "p.poesia"
""",
        encoding="utf-8",
    )
    return cargar_config(tmp_path / "config.toml")
