from __future__ import annotations

import pytest

from bjaudio.errores import TextoInvalido
from bjaudio.texto import LINEA, NINGUNA, PARRAFO, SECCION, VERSICULO, parsear

EJEMPLO = """% comentario que se ignora
# sal 23

## Título editorial
1 El pastor guía al rebaño,
/ nada le falta.
2 Por prados verdes lo lleva

+ y junto a aguas tranquilas.
3 Repara sus fuerzas.
"""


def test_parseo_completo():
    cap = parsear(EJEMPLO)
    assert (cap.libro, cap.numero) == ("sal", 23)
    assert cap.versiculos == ["1", "2", "3"]
    assert [s.titulo for s in cap.secciones] == ["Título editorial"]
    assert [(u.versiculo, u.ruptura, u.inicia_versiculo) for u in cap.unidades] == [
        ("1", SECCION, True),
        ("1", LINEA, False),
        ("2", VERSICULO, True),
        ("2", PARRAFO, False),
        ("3", VERSICULO, True),
    ]


def test_ida_y_vuelta_estable():
    texto = parsear(EJEMPLO).a_texto()
    assert parsear(texto).a_texto() == texto


def test_continuacion_sin_prefijo():
    cap = parsear("# gn 1\n1 Uno.\nsigue sin prefijo\n")
    assert cap.unidades[1].texto == "sigue sin prefijo"
    assert cap.unidades[1].ruptura == NINGUNA


@pytest.mark.parametrize("texto", ["", "1 sin cabecera\n", "# gn 1\ntexto antes de un versículo\n", "# gn 1\n\n",
                                   "# gn 1\n1 Uno.\n2\n"])
def test_errores_claros(texto):
    with pytest.raises(TextoInvalido):
        parsear(texto)


def test_versiculo_con_letra():
    cap = parsear("# dn 3\n24a Texto del añadido griego.\n")
    assert cap.versiculos == ["24a"]
