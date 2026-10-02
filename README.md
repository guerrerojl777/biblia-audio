# biblia-audio

Convierte capítulos de la Biblia, desde **tu EPUB sin DRM**, en MP3 con voz sintética
**verificada**: un capítulo por archivo, con un índice de tiempos por versículo.
Pensado para avanzar de a poco (2–3 capítulos por día) gastando $0.

```
EPUB ──extraer──▶ texto canónico (.txt por capítulo, editable)
                         │
                       plan ──▶ trozos de ~600 caracteres cortados en fin de oración
                         │
              presupuesto (aborta ANTES de llamar si no alcanza el crédito)
                         │
                   síntesis TTS ──caché──▶ verificación ASR (¿dijo todo? ¿agregó algo?)
                         │
             ensamblado: recorte de silencios + pausas propias + volumen normalizado
                         │
             salida/<voz>/01-gn/gn-001.mp3  +  gn-001.json (tiempos por versículo)
```

Todo el control de flujo es código determinístico. Los modelos hacen solo dos tareas
acotadas: sintetizar la voz y transcribirla para verificarla. La salida de un modelo no
se da por buena hasta que la verificación la acepta.

> **Uso personal.** El texto de la Biblia de Jerusalén y sus notas tienen derechos de
> autor. El pipeline no procesa EPUB con DRM ni intenta desprotegerlos, y los audios
> que generes son para ti: no los compartas ni los publiques.

---

## 1. Requisitos

- **Python 3.10 o superior.** Compruébalo con `python3 --version`. Si tu sistema trae
  uno más viejo, instala uno nuevo sin tocar el del sistema con
  [uv](https://docs.astral.sh/uv/): `uv python install 3.12`.
- **ffmpeg**: `sudo apt install ffmpeg`
- Cuentas: Deepgram (motor principal) y, opcional, ElevenLabs (para comparar voces).

## 2. Instalación

```bash
cd biblia-audio
python3 -m venv .venv            # o: uv venv -p 3.12 .venv
source .venv/bin/activate
pip install -r requirements.txt  # opcional: -r requirements-whisper.txt (verificación local)

cp .env.example .env             # y pega tus claves en .env
mkdir -p libros && cp /ruta/a/tu/biblia.epub libros/biblia.epub
```

Alias cómodo para no escribir `python -m bjaudio` cada vez:

```bash
alias bja="python -m bjaudio"
```

En `config.toml`, **pon en `deepgram.credito_usd` el saldo que muestra tu consola de
Deepgram**. El pipeline solo sabe lo que gasta él mismo.

## 3. Receta: un libro de principio a fin (ejemplo: Eclesiastés, `qo`)

Ningún paso gasta crédito salvo los marcados con 💲. Cambia `qo` por el id del libro que
quieras (la lista está en la sección 5).

**1. Que la herramienta entienda tu EPUB** (una sola vez; sirve para todos los libros):

```bash
bja inspeccionar --libro qo
```

Analiza los documentos de ese libro y **deduce** qué elementos marcan capítulos y
versículos por la forma de sus números: los de capítulo crecen de uno en uno y hay tantos
como capítulos (aunque lleven la abreviatura delante: «Qo 3», «1 Cro 3», «SALMO 23 (22)»);
los de versículo crecen de uno en uno y vuelven a empezar en cada capítulo. Detecta
también la poesía (un párrafo por línea) y las estrofas (clases con margen superior en la
CSS). Luego **prueba** la sugerencia extrayendo el libro y la compara con la configuración
actual:

```
## Prueba de extracción
  Configuración actual: 12/12 capítulos · 222 versículos · 0 cortes de línea · …
  Con la sugerencia:    12/12 capítulos · 222 versículos · 178 cortes de línea · …
```

Si la sugerencia gana (más capítulos, o los mismos con mejores pausas), guárdala (deja
copia en `config.toml.bak`):

```bash
bja inspeccionar --libro qo --aplicar
```

El informe queda en `trabajo/inspeccion.txt` y solo trae fragmentos cortos: si algo no
cuadra, compártelo y se ajusta a mano.

> **BJ 2009 convertida con Sigil** (capítulos marcados «Qo 1» en `span.capital`). Esta es
> la configuración probada con la Biblia entera (73 libros, todos los capítulos); el resto
> va por defecto:
>
> ```toml
> [epub]
> archivo = "libros/biblia.epub"
> bloque_corto_chars = 100      # cada línea poética es un <p>
> estrofa = ".top05, .top1"     # clases con margen superior = comienzo de estrofa
> rotulo = ".flm"               # «La amada», «Álef»…: se leen, con pausa larga
> ```
>
> Si prefieres que los rótulos **no** se lean, quita `rotulo` y añade `p.flm` a
> `titulo_seccion` (`"h2, h3, h4, h5, h6, p.flm"`).

**2. Extraer el texto del libro:**

```bash
bja extraer --libro qo
```

Escribe `trabajo/texto/qo/001.txt` … `012.txt` y un informe en `trabajo/extraccion.txt`.
Abre `001.txt` y compáralo con tu Biblia: sin notas, versículos completos, poesía con `/`
al comienzo de cada línea. Si editas un `.txt` a mano, volver a extraer no lo pisa salvo
que uses `--forzar`.

**3. Elegir la voz** (💲 centavos por muestra):

```bash
bja voces --proveedor deepgram
bja muestra "Al principio creó Dios el cielo y la tierra." --voz aura-2-luciano-es
bja muestra "Al principio creó Dios el cielo y la tierra." --voz aura-2-luciano-es --velocidad 0.95
bja voces --proveedor deepgram --usar aura-2-luciano-es      # la deja como predeterminada
```

Coherencia edición–acento: las ediciones de España usan *vosotros*; la Latinoamericana,
*ustedes*. Decide voz y velocidad **antes** de producir el libro: cambiar cualquiera de las
dos regenera (y vuelve a cobrar) todo.

**4. Un capítulo primero, y escucharlo entero:**

```bash
bja plan qo 1                  # cómo se partirá y cuánto costará (no gasta)
bja correr qo 1                # 💲 genera el MP3 verificado
```

El MP3 queda en `salida/deepgram-aura-2-luciano-es/25-qo/qo-001.mp3` (en WSL, ábrelo con
`explorer.exe salida/deepgram-aura-2-luciano-es/25-qo`). Escúchalo completo: una frase
de muestra no dice cómo suena media hora. Revisa nombres propios, ritmo y pausas.

**5. El resto, a tu ritmo:**

```bash
bja correr qo 2-4 --simular    # costo exacto antes de gastar
bja correr qo 2-4              # 💲
bja estado                     # progreso y crédito restante
```

Para extraer **toda** la Biblia de una vez (menos de un minuto): `bja extraer`. La tabla
marca con ← los libros con capítulos de menos; para uno de ellos, `bja inspeccionar --libro <id>`.
El Eclesiástico sale como «51/51 + prólogo»: el prólogo del traductor, que tiene versículos
propios y va antes del capítulo 1, queda en `si/000.txt` y se anuncia «Eclesiástico. Prólogo.»
(`bja correr si 0`).

## 4. Qué dice cada corrida

Cada capítulo imprime su duración, costo y los trozos **marcados**, con el minuto exacto
para ir a escucharlos:

```
! gn 5: 4.1 min · 8 trozos (0 de caché) · $0.1350 · 1 marcados → salida/…/gn-005.mp3
     ↳ trozo 3 (vv. 12–15) en 01:42: faltan 4 palabras seguidas
        falta: "y engendro hijos e hijas"
```

Otras herramientas:

- `bja inspeccionar` (sin `--libro`): panorama de todo el EPUB, títulos reconocidos y
  dudosos, y una prueba con la configuración actual.
- `bja inspeccionar --doc 54`: estructura de un documento concreto (número de la lista).
- `bja correr gn 1 --proveedor simulado --asr simulado`: la tubería completa con tonos en
  vez de voz, a $0.

## 5. Formato canónico (`trabajo/texto/<libro>/<NNN>.txt`)

Es la frontera entre conseguir el texto y producir audio. Lo puedes crear a mano si un
libro no sale bien del EPUB.

```
# sal 23                 cabecera: id del libro y capítulo (obligatoria; 0 = prólogo)
## Título de sección     editorial: NO se lee; va al índice
(línea vacía)            separa párrafos → pausa larga
1 Texto…                 empieza el versículo 1 (también 1a, 40ab, o 24-25 si la edición los une)
0 Texto…                 texto antes del versículo 1 (p. ej. un «¡Aleluya!» sin número)
/ Texto…                 nueva línea poética del mismo versículo → pausa corta
+ Texto…                 continúa el versículo tras un salto de párrafo
% comentario             se ignora (la extracción anota así los versículos entre corchetes)
```

Antes de pedir el audio, las cantidades en cifras pasan a palabras y concuerdan con lo
que sigue («21 hombres» → «veintiún hombres», «675.000 ovejas» → «seiscientas setenta y
cinco mil ovejas»), y las palabras en mayúsculas pasan a minúsculas con inicial: así ningún
motor lee un número como decimal ni deletrea lo que parece una sigla. El `.txt` no cambia.

Volver a extraer actualiza los `.txt` que escribió la extracción y nadie tocó, y **respeta
los que editaste** (lo sabe por `trabajo/texto/.huellas.json`). Un `.txt` de una versión
anterior se respeta igual: si no lo editaste, regenéralo con `--forzar`.

Los ids de libro son `gn ex lv nm dt jos jc rt 1s 2s 1r 2r 1cro 2cro esd ne tb jdt est 1m 2m
jb sal pr qo ct sb si is jr lm ba ez dn os jl am abd jon mi na ha so ag za ml mt mc lc jn hch
rm 1co 2co ga ef flp col 1ts 2ts 1tm 2tm tt flm hb st 1p 2p 1jn 2jn 3jn jds ap`.

## 6. Verificación: qué detecta y qué no

Cada trozo se transcribe con un reconocedor de voz y se alinea palabra por palabra con el
texto pedido. El criterio principal son las **rachas**:

- Un reconocedor se equivoca de forma dispersa (una palabra suelta, sobre todo nombres
  propios). Eso no marca nada.
- Un motor que **se salta** una frase deja una racha de palabras faltantes. Un motor que
  **repite o inventa** deja una racha de palabras sobrantes. Eso sí se marca.

La misma alineación da el **tiempo de inicio de cada versículo** (`gn-001.json`).

Límites honestos:

- El reconocedor escribe lo que *debería* haberse dicho. Detecta muy bien omisiones e
  inserciones, y mal un nombre pronunciado raro. Los nombres se cuidan con el léxico y
  escuchando.
- Deepgram describe Aura-2 como sensible al contexto, capaz de añadir pausas y muletillas.
  Las muletillas («eh», «mm») normalmente no aparecen en la transcripción, así que podrían
  pasar sin marca. Si oyes alguna, repórtala en el piloto.
- Con ElevenLabs un trozo marcado se regenera con otra semilla (`reintentos`) y se queda el
  mejor intento. Con Deepgram repetir suele dar el mismo audio: corrige el texto o el léxico
  y vuelve a correr.

Al volver a correr un capítulo, la caché hace que **solo se regeneren y se cobren los trozos
cuyo texto cambió**.

## 7. Presupuesto ($0)

Antes de llamar a cualquier API, el pipeline estima el costo de los trozos que no están en
caché. Si no cabe en lo disponible, aborta sin llamar.

- **Deepgram:** `credito_usd − reserva_usd − lo gastado` según `trabajo/gastos.jsonl`.
- **ElevenLabs:** un tope mensual local (`creditos_mes`) y, si hay clave, la cuota real que
  informa su API.

Orden de magnitud con los precios de octubre de 2026 (Aura-2 a $0.030 por cada 1000
caracteres; Nova-3 a $0.0043 por minuto), medido sobre la BJ 2009 completa extraída (los
minutos son una estimación a ~14 caracteres por segundo):

| | Eclesiastés (12 cap., ~25 mil caracteres, ~30 min) | Capítulo promedio (~3,2 mil car., ~4 min) | Biblia completa (~4,3 M car., ~85 h) |
|---|---|---|---|
| Voz (Aura-2) | ~$0.75 | ~$0.10 | ~$129 |
| Verificación (Nova-3) | ~$0.13 | ~$0.02 | ~$22 |

Con el crédito inicial de $200 alcanza para toda la Biblia verificada, con algo de margen.
Para ganar margen, verifica en local y gratis con Whisper:
`pip install -r requirements-whisper.txt` y `asr = "whisper"`. Es más lento en CPU, pero para
2–3 capítulos al día sobra.

## 8. Motores

**Deepgram Aura-2 (recomendado aquí).** Tiene voces en español de España, México, Colombia,
Argentina y Latinoamérica. Acepta hasta 2000 caracteres por petición y velocidad entre 0.7 y
1.5 (en español se recomienda 0.9–1.5). Permite pronunciación por IPA en línea. No tiene
control de pausas: las pausas las pone este pipeline al ensamblar.

**ElevenLabs.** Prosodia muy natural. El plan gratuito trae unos 10 000 créditos al mes, de
uso no comercial y con atribución: alcanza para comparar voces en el piloto, no para el día a
día. `language_code` no se envía con `eleven_multilingual_v2` porque ese modelo no lo admite.

**Modal (fase 2).** Sus $30 mensuales de crédito sirven para correr un modelo abierto en GPU
cuando se acabe el crédito de Deepgram. Agregarlo es un archivo nuevo en
`bjaudio/proveedores/` que implemente `ProveedorTTS`. Conviene hacerlo con datos del piloto
y no antes.

## 9. Léxico de pronunciación (`lexico.tsv`)

```
palabra<TAB>reescritura<TAB>IPA (opcional)
Qohélet	Coélet
Yahvé	-	ʝaβˈe
```

- La **reescritura** sirve con cualquier motor.
- El **IPA** solo lo usa Deepgram. En Aura-2, la marca de acento va justo antes de la vocal.
  Se factura la palabra, no el IPA.
- Agrega entradas solo después de escuchar un error. Cambiar el léxico regenera solo los
  trozos afectados.

## 10. Carpetas

```
config.toml        lexico.tsv        .env (tus claves; no se sube)
config.toml.bak    copia automática antes de cada --aplicar / --usar
libros/            tu EPUB
trabajo/texto/     .txt canónicos por capítulo (puedes editarlos)
trabajo/           inspeccion.txt, extraccion.txt, gastos.jsonl, verificacion/
cache/             audio por trozo (borrarla = volver a pagar)
salida/<voz>/      MP3 + índice JSON por capítulo; muestras/
```

## 11. Problemas frecuentes

- **«Este EPUB tiene DRM»:** el pipeline no lo procesa. Puedes escucharlo con la lectura en
  voz alta de tu app de lectura, pedir permiso a la editorial o usar una edición sin DRM.
- **Avisos de «número suelto» o «tramo de 1500+ caracteres»:** un selector no está
  capturando los versículos o capítulos, o se coló una nota. Vuelve a
  `bja inspeccionar --libro <id>`. Las cantidades del texto («los de Ará: 775») no avisan:
  van a «Para tu información» y se leen en palabras.
- **«Capítulo descartado: ningún versículo numerado con texto»:** normal en
  introducciones, que citan capítulos en negrita («véase 3 1-8»). Se descartan solos.
- **«N trozos con el mismo número de capítulo y versículos distintos»:** la BJ traspone
  versículos (1 R 4–5, el añadido griego al comienzo de Ester 1). Los trozos se unen en el
  orden del libro y el capítulo queda completo; el aviso dice qué versículos trae cada trozo.
- **«Descarto un duplicado» / «descarto un trozo sin marca de capítulo»:** un capítulo que
  repite versículos de otro, o un número suelto en una introducción. Se queda el bueno.
- **«Cambio(s) de orden» y «versículos repetidos»:** en la BJ son traspuestos dentro del
  capítulo (Job, Zacarías 4…) o numeración doble (Daniel 3, con el añadido griego: en el
  índice JSON el segundo «24» aparece como «24#2»). Se lee en el orden del libro.
- **«Faltan versículos» en el Eclesiástico:** son los versículos del texto griego largo
  (1,5; 26,19-27…), que esta edición no trae en el cuerpo del texto. En otros libros, mira
  el EPUB: si falta solo el número (Juan 5,15 en la BJ 2009 de Sigil), el texto está,
  pegado al versículo anterior.
- **Versículos entre corchetes** («[21]» en Mt 17): la BJ los omite del texto. No se leen,
  no cuentan como faltantes y quedan anotados con `%` en el `.txt`.
- **Un título dentro de un libro corta la extracción** («N marcas de capítulo después del
  título …»): decláralo en `[epub.titulos]` con el valor `"seccion"`.
- **Títulos sin ordinal** («SAMUEL», «REYES»): se toman como el primer libro de la serie;
  el informe los lista en «Títulos para revisar» por si tu edición los usa distinto.
- **Títulos de Salmos:** en la numeración hebrea, el título de un salmo suele ser el
  versículo 1. Si tu EPUB lo marca con una clase propia, no la pongas en `titulo_seccion`,
  porque se perdería texto bíblico. Los encabezados dobles («SALMO 9-10») funcionan: el
  segundo salmo empieza en su propia marca («Sal 10»).
- **Ester y Daniel** tienen añadidos griegos con numeración especial (1a, 1b…; Dn 3,24-90).
  Se extraen completos; revisa sus avisos con calma la primera vez.
- **Cambié de voz y se regeneró todo:** es lo esperado. La voz forma parte de la clave de
  caché, y cada voz tiene su carpeta de salida, así que comparar no pisa nada.

## 12. Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Las pruebas usan un EPUB sintético con texto inventado, APIs simuladas y ffmpeg real.
No llaman a ninguna API ni gastan crédito.
