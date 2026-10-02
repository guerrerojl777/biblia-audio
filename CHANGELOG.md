# Cambios

## 0.3.2

Para la erre final que algunas voces convierten en «rz» («mar» suena «marzo»).

- `bja probar-erre [--voz gloria]`: un MP3 con la misma frase (inventada, con erre final
  ante coma, ante consonante, ante vocal, al final y en «por») en cuatro versiones: como
  ahora, erre simple en IPA [ɾ], erre múltiple en IPA [r] y «rr» escrita. Unos 2 centavos.
- `[deepgram] erre_final = "suave" | "fuerte" | "rr"` aplica la opción elegida a todas las
  palabras terminadas en *r*. El IPA sale de reglas del español (seseo o distinción según la
  voz); no se cobra y no toca el `.txt` ni la verificación. Las entradas del léxico mandan.
- Si las marcas de IPA alargaran un trozo más allá de 2000 caracteres, se pide en partes y
  se une el audio (con la Biblia entera no pasa: el trozo más largo queda en 1761).

## 0.3.1

Para elegir voz comparando el mismo capítulo.

- `bja correr` y `bja plan` aceptan `--voz` y `--velocidad` solo para esa orden:
  `bja correr qo 1 --voz javier`. config.toml no cambia.
- Nombres cortos de voz: `luciano` es `aura-2-luciano-es` (en `--voz`, `muestra` y
  `voces --usar`). Un nombre mal escrito lista las opciones.
- La carpeta de salida incluye la velocidad cuando no es 1.0
  (`salida/deepgram-aura-2-javier-es-x0.95/`): comparar ritmos ya no sobrescribe el MP3.
  A velocidad 1.0 la carpeta es la de siempre.

## 0.3.0

Hecha con el EPUB real (BJ 2009 convertida con Sigil). Con la 0.2, Eclesiastés salía con
1 de 12 capítulos; ahora salen los 73 libros completos (1328 capítulos + el prólogo del
Eclesiástico) en menos de un minuto.

**Capítulos**
- Marcas con abreviatura delante: «Qo 3», «1 Cro 3», «Sal 10» (`span.capital`,
  `span.salmocapital`, ya incluidas por defecto). La regex por defecto acepta además
  «Salmo 23 (22)» y «SALMO 9-10».
- El inspector reconoce esas marcas en cualquier etiqueta, comprueba que la regex
  configurada sepa leerlas (si no, propone la nueva) y completa huecos con otra clase de
  marca («SALMO 9-10» + «Sal 10»). Descarta candidatos sin versículos entre medio, como el
  índice interno de cada libro.
- Versículos traspuestos (1 R 4–5, Ester 1): los trozos con el mismo número de capítulo y
  versículos distintos se unen en el orden del libro. La 0.2 se quedaba con uno y perdía
  texto. Si un trozo empieza con texto sin número, sigue el versículo donde quedó el
  capítulo. Un trozo que se descarta y trae versículos que no están en el capítulo
  conservado se avisa con «¡OJO!» y la lista de versículos: nunca se pierde texto en silencio.
- El prólogo del Eclesiástico (versículos propios antes del capítulo 1, sin marca, con
  título «Prólogo…») pasa a ser el capítulo 0, «Eclesiástico. Prólogo.». La 0.2 lo descartaba.
  Una introducción con llamadas de nota numeradas no cuenta como prólogo, y un capítulo 1
  sin marca seguido de un trozo traspuesto marcado se une a él.
- Un capítulo necesita al menos un versículo numerado con texto: una referencia de una
  introducción seguida de una llamada de nota numérica ya no cuenta.
- Un título de libro se prueba también con espacios entre etiquetas
  (<span>CARTA A LOS</span><span>ROMANOS</span>) si sin ellos no se reconoce.

**Versículos**
- Etiquetas con dos letras («40ab»), unidas («24-25») y entre corchetes sin texto
  («[21]», «[7] 8»): estas no se leen, no cuentan como faltantes y quedan anotadas con `%`.
- Texto entre la marca de capítulo y el versículo 1 (1 S 11, Ne 8, Ag 2, aclamaciones de
  los salmos): versículo 0, en vez de un «1» repetido.
- Numeración doble (Dn 3): en el índice JSON, «24#2» para la segunda aparición, también
  dentro de un mismo trozo de audio.

**Lectura**
- Cantidades en cifras → palabras antes de pedir el audio («2.172» → «dos mil ciento
  setenta y dos»), concordando con el sustantivo que sigue («veintiún hombres»,
  «seiscientas setenta y cinco mil ovejas», «el tercer día»). La verificación compara igual
  «46.500», «46,500» y la forma en palabras.
- Palabras en mayúsculas → minúsculas con inicial («LA AMADA» → «La Amada»), antes del
  léxico (así una entrada también vale para la palabra en mayúsculas). Los números romanos
  y las siglas cortas quedan como están.
- `rotulo`: bloques que se leen con pausa larga antes y después (quién habla en el Cantar,
  letras de los acrósticos).
- Un bloque que solo trae un número romano («I»… «V» en Habacuc) es un título editorial.
- Títulos sin espacios inventados: versalitas («LA AMADA», no «L A AMADA») y punto
  pegado tras una llamada de nota eliminada («Prólogo.»).
- El inspector propone mejoras de pausas (líneas y estrofas) aunque los capítulos ya
  salgan bien, y suma clases de estrofa nuevas a las configuradas.

**Seguridad al actualizar**
- `trabajo/texto/.huellas.json` recuerda lo que escribió la extracción: volver a extraer
  actualiza los `.txt` que nadie tocó y respeta los editados a mano. Uno de origen
  desconocido (p. ej. de la 0.2) solo se pisa con `--forzar`, y el aviso lo explica.
- `bja plan`/`bja correr` se niegan a procesar un capítulo con tres «1» (un `.txt` viejo con
  varios capítulos dentro): mejor parar que pagar el libro entero dos veces.

**Informe**
- «Para tu información»: cantidades en cifras, versículos entre corchetes, prólogo.
- «Número suelto» solo avisa de lo que parece una marca sin detectar («…dijo. 5 Entonces»,
  «Qo 2» suelto); las cantidades del texto ya no avisan.
- Mensajes distintos para traspuestos unidos, duplicados y trozos sin marca descartados.
- `bja extraer` y `bja estado` muestran «+ prólogo»; el MP3 del prólogo no lleva número
  de pista.

## 0.2.0

Hecha a partir de la primera inspección de un EPUB real (272 documentos, notas en
documentos aparte, títulos «Notas | …»).

**Inspección que decide, no solo informa**
- `bja inspeccionar --libro qo`: analiza los documentos de un libro, deduce qué elemento
  marca los capítulos y cuál los versículos por la forma de sus números, detecta poesía
  (un párrafo por línea) y estrofas (clases con margen superior en la CSS), prueba la
  sugerencia extrayendo el libro y la compara con la configuración actual.
- `--aplicar` guarda la sugerencia en `config.toml` (copia en `config.toml.bak`; valida
  antes de escribir y restaura si algo falla). Activa las claves comentadas de la
  plantilla en su sitio.
- `--doc N`: estructura de un documento concreto.
- El informe general ya no elige un documento de notas para el esqueleto.

**Extracción más robusta**
- Los títulos «Notas…» cierran el libro (`ignorar_titulos`): las notas nunca se cuelan.
- Capítulo 1 sin marca: se asume al ver el versículo 1 (y los libros de un solo capítulo
  ya no se pierden).
- Los capítulos sin ningún número de versículo se descartan (referencias en negrita de
  las introducciones) y los duplicados se resuelven quedándose con el más sólido.
- Los títulos de sección que van justo antes del número de capítulo pasan al capítulo
  correcto.
- «SAMUEL», «REYES», «LOS LIBROS DE LAS CRÓNICAS» se reconocen como el primer libro de la
  serie; el informe los lista para revisar. `[epub.titulos]` acepta `"seccion"`.
- `bloque_corto_chars`: los párrafos cortos seguidos se leen como líneas de un mismo
  párrafo poético.
- `bja extraer --libro X` recorre solo los documentos de ese libro (segundos, no minutos).
- El informe compara capítulos encontrados con los esperados de cada libro y avisa de
  letras griegas o hebreas que la voz no leería bien.

**CLI**
- `bja voces --usar aura-2-luciano-es` deja la voz como predeterminada.
- `bja muestra … --velocidad 0.95` para comparar ritmos.
- `bja correr` sin texto extraído explica qué ejecutar antes.
