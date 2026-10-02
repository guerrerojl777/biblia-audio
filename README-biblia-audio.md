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

## 3. Primer uso, en orden

Ningún paso de esta sección gasta crédito salvo los marcados con 💲.

**1. Inspeccionar el EPUB.**

```bash
bja inspeccionar
```

Primero dice si tiene DRM. Si lo tiene, aquí termina el camino del pipeline. Si no, muestra
qué etiquetas y clases usa tu EPUB para números de versículo, llamadas de nota y títulos,
y prueba la configuración actual. El informe queda en `trabajo/inspeccion.txt`. Solo trae
fragmentos de 24 caracteres, así que puedes compartirlo para ajustar los selectores.

**2. Ajustar `[epub]` en `config.toml`** con lo que mostró la inspección. Por ejemplo, si
los versículos son `<span class="vers">` y las notas `<a class="llamada">`:

```toml
[epub]
versiculo = "span.vers"
eliminar = ["a.llamada", "div.notas"]
linea_poetica = "p.poesia"
```

Repite `inspeccionar` hasta que la «Prueba con la configuración actual» salga limpia.

**3. Extraer.**

```bash
bja extraer
```

Escribe `trabajo/texto/<libro>/<NNN>.txt` y un informe de avisos en
`trabajo/extraccion.txt`: versículos faltantes, números sueltos en el texto o tramos
sospechosamente largos (una nota que se coló). Si editas un `.txt` a mano, volver a extraer
no lo pisa salvo que uses `--forzar`.

**4. Probar la tubería completa gratis**, con el motor simulado (tonos en vez de voz):

```bash
bja correr gn 1 --proveedor simulado --asr simulado
```

**5. 💲 Escuchar voces** con una frase tuya (cuesta centavos):

```bash
bja voces --proveedor deepgram
bja voces --proveedor deepgram --usar aura-2-luciano-es
bja voces --proveedor deepgram --usar aura-2-javier-es
bja voces --proveedor deepgram --usar aura-2-gloria-es

bja correr qo 1

bja correr qo 2-12

bja muestra "Al principio creó Dios el cielo y la tierra." --voz aura-2-alvaro-es
bja muestra "Al principio creó Dios el cielo y la tierra." --voz aura-2-javier-es
```

Las muestras quedan en `salida/muestras/`. Coherencia edición–acento: las ediciones de
España usan *vosotros*, así que pide una voz de España; la Latinoamericana usa *ustedes*,
así que pide una de México o es-419.

**6. 💲 Piloto: escuchar antes de comprometerse.** Antes de producir en serie, genera unos
pocos capítulos que cubran los casos difíciles: narración con diálogo (Rut 1), poesía (un
salmo largo, Isaías 40), ráfagas de nombres (1 Crónicas 1, Mateo 1), cifras (Números 1) y
frases largas (Romanos 8). Antes de escucharlos, decide qué es «bien»: cero omisiones,
nombres que se entiendan, poder escuchar media hora sin cansarte.

## 4. Uso diario

```bash
bja plan gn 4                 # cómo se partirá y cuánto costará (no gasta)
bja correr gn 4-6 --simular   # costo de varios capítulos (no gasta)
bja correr gn 4-6             # 💲 genera los MP3
bja estado                    # progreso por libro y crédito restante
```

Cada capítulo imprime su duración, costo y los trozos **marcados**, con el minuto exacto
para ir a escucharlos:

```
! gn 5: 4.1 min · 8 trozos (0 de caché) · $0.1350 · 1 marcados → salida/…/gn-005.mp3
     ↳ trozo 3 (vv. 12–15) en 01:42: faltan 4 palabras seguidas
        falta: "y engendro hijos e hijas"
```

## 5. Formato canónico (`trabajo/texto/<libro>/<NNN>.txt`)

Es la frontera entre conseguir el texto y producir audio. Lo puedes crear a mano si un
libro no sale bien del EPUB.

```
# sal 23                 cabecera: id del libro y capítulo (obligatoria)
## Título de sección     editorial: NO se lee; va al índice
(línea vacía)            separa párrafos → pausa larga
1 Texto…                 empieza el versículo 1 (también 1a, 1b…)
/ Texto…                 nueva línea poética del mismo versículo → pausa corta
+ Texto…                 continúa el versículo tras un salto de párrafo
% comentario             se ignora
```

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
caracteres; Nova-3 a $0.0043 por minuto):

| | Por capítulo promedio (~3,8 mil caracteres, ~4,5 min) | Biblia completa (~4,5–5,5 M caracteres) |
|---|---|---|
| Voz (Aura-2) | ~$0.11 | ~$135–165 |
| Verificación (Nova-3) | ~$0.02 | ~$23–28 |

Con el crédito inicial de $200 alcanza, con poco margen, para toda la Biblia verificada.
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
libros/            tu EPUB
trabajo/texto/     .txt canónicos por capítulo (puedes editarlos)
trabajo/           inspeccion.txt, extraccion.txt, gastos.jsonl, verificacion/
cache/             audio por trozo (borrarla = volver a pagar)
salida/<voz>/      MP3 + índice JSON por capítulo; muestras/
```

## 11. Problemas frecuentes

- **«Este EPUB tiene DRM»:** el pipeline no lo procesa. Puedes escucharlo con la lectura en
  voz alta de tu app de lectura, pedir permiso a la editorial o usar una edición sin DRM.
- **Avisos de «números sueltos» o «tramo de 1500+ caracteres»:** un selector no está
  capturando los versículos o se coló una nota. Vuelve a `inspeccionar`.
- **Títulos de Salmos:** en la numeración hebrea, el título de un salmo suele ser el
  versículo 1. Si tu EPUB lo marca con una clase propia, no la pongas en `titulo_seccion`,
  porque se perdería texto bíblico.
- **Ester y Daniel** tienen añadidos griegos con numeración especial. Revisa sus avisos de
  extracción con calma.
- **Cambié de voz y se regeneró todo:** es lo esperado. La voz forma parte de la clave de
  caché, y cada voz tiene su carpeta de salida, así que comparar no pisa nada.

## 12. Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Las pruebas usan un EPUB sintético con texto inventado, APIs simuladas y ffmpeg real.
No llaman a ninguna API ni gastan crédito.
