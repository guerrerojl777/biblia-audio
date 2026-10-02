from __future__ import annotations

import pytest

from bjaudio.config import cargar_config
from bjaudio.epub import Epub
from bjaudio.errores import EpubProtegidoError
from bjaudio.extraccion import extraer, extraer_a_disco
from bjaudio.texto import LINEA, PARRAFO, SECCION, VERSICULO, leer, parsear, ruta_capitulo

from .conftest import GENESIS, crear_epub

ENC_CONTENIDO = """<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
  xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <enc:EncryptedData><enc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/>
  <enc:CipherData><enc:CipherReference URI="OEBPS/gn.xhtml"/></enc:CipherData></enc:EncryptedData>
</encryption>"""

ENC_FUENTES = """<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
  xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <enc:EncryptedData><enc:EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/>
  <enc:CipherData><enc:CipherReference URI="OEBPS/fuentes/letra.otf"/></enc:CipherData></enc:EncryptedData>
</encryption>"""


def test_drm_adobe_se_rechaza(tmp_path):
    ruta = crear_epub(tmp_path / "x.epub", {"gn.xhtml": GENESIS}, {"META-INF/rights.xml": "<rights/>"})
    with Epub(ruta) as e:
        assert e.drm.protegido
        with pytest.raises(EpubProtegidoError):
            extraer(e, cargar_config(tmp_path / "no-existe.toml").epub)


def test_contenido_cifrado_es_drm(tmp_path):
    ruta = crear_epub(tmp_path / "x.epub", {"gn.xhtml": GENESIS}, {"META-INF/encryption.xml": ENC_CONTENIDO})
    with Epub(ruta) as e:
        assert e.drm.protegido
        assert "gn.xhtml" in e.drm.motivo


def test_fuentes_ofuscadas_no_son_drm(tmp_path):
    ruta = crear_epub(tmp_path / "x.epub", {"gn.xhtml": GENESIS}, {"META-INF/encryption.xml": ENC_FUENTES})
    with Epub(ruta) as e:
        assert not e.drm.protegido
        assert e.drm.fuentes_ofuscadas == 1


def test_extraccion_estructura(proyecto):
    with Epub(proyecto.ruta_epub()) as e:
        res = extraer(e, proyecto.epub)
    assert [(c.libro, c.numero) for c in res.capitulos] == [("gn", 1), ("gn", 2)]
    cap1, cap2 = res.capitulos
    assert cap1.versiculos == ["1", "2", "3", "4", "5"]
    textos = [u.texto for u in cap1.unidades]
    # la llamada de nota desaparece y el ancla vacía no se traga texto
    assert textos[0] == "Al principio la luz llenó la casa."
    assert textos[1] == "La mesa estaba servida, y el pan seguía tibio."
    assert textos[2] == "Dijo el vecino: «Que haya fiesta»."
    # sección antes del primer versículo; párrafo antes del 4; línea poética en el 5
    assert [(s.titulo, s.antes_de) for s in cap1.secciones] == [("El comienzo", 0)]
    rupturas = [u.ruptura for u in cap1.unidades]
    assert rupturas == [SECCION, VERSICULO, VERSICULO, PARRAFO, PARRAFO, LINEA]
    assert cap1.unidades[-1].texto == "y el río responde al amanecer."
    assert not cap1.unidades[-1].inicia_versiculo
    # capítulo que empieza sin número: versículo 1 implícito
    assert cap2.versiculos == ["1", "2"]
    todo = " ".join(u.texto for c in res.capitulos for u in c.unidades)
    assert "Introducción" not in todo and "editor" not in todo  # intro y notas fuera
    assert res.caracteres_ignorados > 0


def test_canonico_ida_y_vuelta(proyecto):
    with Epub(proyecto.ruta_epub()) as e:
        res = extraer(e, proyecto.epub)
    for cap in res.capitulos:
        texto = cap.a_texto()
        assert parsear(texto).a_texto() == texto
    assert res.capitulos[0].a_texto() == (
        "# gn 1\n\n## El comienzo\n"
        "1 Al principio la luz llenó la casa.\n"
        "2 La mesa estaba servida, y el pan seguía tibio.\n"
        "3 Dijo el vecino: «Que haya fiesta».\n\n"
        "4 Y hubo fiesta hasta la noche.\n\n"
        "5 Canta la tierra con su gente\n"
        "/ y el río responde al amanecer.\n"
    )


def test_no_pisa_ediciones_sin_forzar(proyecto):
    extraer_a_disco(proyecto)
    ruta = ruta_capitulo(proyecto.dir_texto, "gn", 1)
    editado = ruta.read_text(encoding="utf-8").replace("la casa", "la casa grande")
    ruta.write_text(editado, encoding="utf-8")
    _, (nuevos, _iguales, omitidos) = extraer_a_disco(proyecto)
    assert nuevos == 0 and len(omitidos) == 1
    assert "la casa grande" in ruta.read_text(encoding="utf-8")
    extraer_a_disco(proyecto, forzar=True)
    assert "la casa grande" not in ruta.read_text(encoding="utf-8")
    assert leer(ruta).versiculos == ["1", "2", "3", "4", "5"]
