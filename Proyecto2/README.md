# Dataset Quality & Versioning

Plataforma de **calidad y versionado** para el dataset de detección de objetos
(formato COCO) producido por el proyecto de anotación (MP1).

Analiza el dataset crudo, aplica una **compuerta de calidad** que puede bloquear
la publicación, genera los splits estratificados y publica versiones inmutables
y content-addressed hacia MinIO en local / S3 en producción.

Stack: Python 3.12 · FastAPI · pydantic-settings · SQLAlchemy sobre MariaDB ·
MinIO (S3-compatible) · Docker Compose · Ruff · pytest.

---

## Requisitos previos

- **Docker Desktop** (Compose v2) instalado y corriendo.
- **Python 3.12** en el host, únicamente para lanzar el comando de arranque.
  `scripts/up.py` usa solo la librería estándar: no hace falta crear un entorno
  virtual ni instalar dependencias para levantar el proyecto.

No se necesita nada más. Sin Node, sin `pip install` previo, sin pasos manuales.

## Puesta en marcha desde cero

Desde un clon limpio, estos son **todos** los comandos necesarios:

```bash
git clone <url-del-repo> Proyecto-3-Clasificador-de-imagenes
cd Proyecto-3-Clasificador-de-imagenes/Proyecto2
python scripts/up.py
```

`python scripts/up.py` es el punto único de arranque. Orquesta la secuencia
completa sin intervención manual:

1. Si no existe `.env`, lo crea copiando `.env.example`. Los valores por defecto
   funcionan para el entorno local; no se versiona ningún `.env` real.
2. Construye las imágenes y levanta los servicios — **app + MariaDB + MinIO**,
   más **MLflow y el worker de entrenamiento** del Proyecto 3 — esperando a que
   reporten `healthy` (`docker compose up -d --build --wait`).
3. Crea los buckets de MinIO con un job idempotente (`minio-init`).
4. Consulta `/health` y **falla con código distinto de cero** si MariaDB o MinIO
   no responden desde dentro de la app. No basta con que el contenedor exista.
5. Espera a que MLflow responda en `/health`.
6. Imprime las URLs de trabajo.

> La primera ejecución descarga las imágenes base de Docker y compila la imagen
> de la app; tarda unos minutos. Las siguientes son cuestión de segundos.

Al terminar verás:

```
Entorno listo.

  App / UI          http://localhost:8000
  OpenAPI           http://localhost:8000/docs
  Health            http://localhost:8000/health
  Consola MinIO     http://localhost:9101   (usuario y clave en .env)
  MLflow            http://localhost:5000
```

### Puertos

| Recurso        | URL / puerto             | Variable en `.env`    |
| -------------- | ------------------------ | --------------------- |
| App / UI       | `http://localhost:8000`  | `APP_PORT`            |
| MariaDB        | `localhost:3307`         | `DB_PORT`             |
| MinIO (API)    | `localhost:9100`         | `MINIO_PORT`          |
| MinIO (consola)| `http://localhost:9101`  | `MINIO_CONSOLE_PORT`  |
| MLflow         | `http://localhost:5000`  | `MLFLOW_PORT`         |

Los puertos están corridos a propósito respecto al proyecto de anotación
(3306 / 9000 / 9001) para que ambos entornos convivan en la misma máquina.

### Otros comandos

```bash
python scripts/up.py --logs      # al terminar, sigue los logs de la app
python scripts/up.py --no-build  # no reconstruye la imagen (arranque rápido)
python scripts/up.py --fresh     # borra volúmenes y empieza de cero
python scripts/down.py           # apaga y conserva los datos
python scripts/down.py --volumes # apaga y borra los datos (pide confirmación)
```

El código de `src/` está montado en vivo dentro del contenedor: al guardar un
archivo, uvicorn recarga solo.

---

## Configuración: cero credenciales en el código

Toda la configuración entra por variables de entorno, y en local esas variables
salen de un único archivo `.env`. Hay tres capas que lo hacen cumplir, y ninguna
es una promesa: las tres fallan ruidosamente.

### 1. `src/dataset_quality/settings.py` — pydantic-settings

Un modelo `BaseSettings` con tipos estrictos. Las credenciales son `SecretStr` y
**no tienen valor por defecto**. Si falta una, el proceso aborta al arrancar:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
db_password
  Field required [type=missing, ...]
```

`SecretStr` además impide el filtrado accidental: la contraseña no aparece en
`repr()`, ni en los logs, ni en el endpoint `/api/config`. Hay una prueba que lo
verifica (`tests/test_settings.py`).

### 2. `docker-compose.yml` — sin valores por defecto

Usa la sintaxis `${VAR:?mensaje}`. Si la variable no está en `.env`, Compose se
niega a arrancar en vez de levantar la base de datos con una contraseña que
alguien podría adivinar:

```
$ docker compose config
error while interpolating services.mariadb.environment.MARIADB_PASSWORD:
required variable DB_PASSWORD is missing a value: falta DB_PASSWORD en .env
```

### 3. `.gitignore` y `.dockerignore`

`.env` está en ambos: nunca se commitea ni entra en la imagen. Lo único
versionado es la plantilla `.env.example`, con valores de desarrollo.

### La excepción, y por qué no es un secreto

Compose fija a mano cuatro variables para el servicio `app`:

```yaml
DB_HOST: mariadb
DB_PORT: "3306"
MINIO_ENDPOINT: minio
MINIO_PORT: "9000"
```

Son **topología de red interna** de Docker, no configuración secreta: dentro de
la red de Compose los servicios se llaman por su nombre. Gracias a eso, `.env`
puede seguir apuntando a `localhost` para cuando corras la app fuera de Docker.

`GET /api/config` devuelve la configuración efectiva **sin secretos**, útil para
verificar contra qué base y qué bucket está trabajando el entorno.

---

---

## Dataset Copilot (MCP)

La pantalla **Copilot** consulta exclusivamente los artefactos ya producidos
por el pipeline. Para activarla, agrega una clave de Gemini a tu `.env`:

```bash
GEMINI_API_KEY=...
# GEMINI_MODEL=gemini-flash-latest  # configurable
```

Al arrancar con Compose, el servidor MCP vive en un contenedor interno sin
puerto publicado. Solo la API puede usar sus cinco herramientas de lectura:
calidad, checks fallidos, distribución de clases, splits y versiones. Cada
respuesta muestra las llamadas ejecutadas y cita el artefacto con su revisión
SHA-256. Cuando la huella del dataset de ese reporte coincide exactamente con
una entrada de `versions.json`, la cita también muestra la versión publicada
(`vX.Y.Z`); si no hay coincidencia o el registro de versiones no está disponible,
la cita conserva la huella y deja la versión vacía. MariaDB guarda una auditoría
de las llamadas, no de las conversaciones.

Si la clave no está configurada, el resto de la plataforma sigue disponible y
el endpoint del Copilot devuelve `503` con la instrucción de configuración.

## Traer el dataset del Proyecto 1

El portal de anotacion expone su dataset por HTTP. Este script lo descarga a
`data/raw/` — que es donde el pipeline lo busca — y de paso **verifica el
minimo del curso**: al menos 300 imagenes distintas en al menos 2 clases.

```bash
# El Proyecto 1 tiene que estar levantado (npm run up en su repositorio)
python scripts/export_from_mp1.py
```

| Opcion | Para que |
| ------ | -------- |
| `--check-only` | Solo consulta el conteo por clase; no descarga nada. Rapido, para el seguimiento diario. |
| `--strict` | Sale con codigo 1 si el minimo no se cumple. Util en CI. |
| `--fresh` | Borra las imagenes locales antes de descargar. |
| `--base-url URL` | Apunta a otro host (por defecto, `MP1_BASE_URL` del `.env`). |

La descarga es **reanudable**: si se corta, vuelve a correr el script y retoma
donde se quedo en vez de empezar de cero.

### Despues de exportar: versionar el dataset

El script deja el dataset en disco, pero no lo versiona. Ese es un paso
aparte, y hay que darlo una vez por cada version del dataset:

```bash
dvc add data/raw                 # calcula el hash del directorio -> data/raw.dvc
dvc push data/raw.dvc            # sube el contenido al remote activo (dev)
dvc push -r prod data/raw.dvc    # y a S3
git add data/raw.dvc .gitignore
```

**El puntero en el `push` no es opcional.** `dvc push` a secas recorre las
etapas de `dvc.yaml`, y todas sus salidas son `cache: false`, asi que no sube
nada: imprime `Everything is up to date` y sale con codigo 0 aunque el bucket
este vacio. Verificado: con el bucket de prod recien creado, `dvc push -r prod`
reporto exito y subio 0 objetos; `dvc push -r prod data/raw.dvc` subio los 840.

`data/raw.dvc` (112 bytes) es lo unico que entra a Git; las 838 imagenes
viven en el remote. Quien clona el repo **no necesita el Proyecto 1
levantado**: le basta `dvc pull` para reconstruir `data/raw/` byte a byte. El
job `versionado` del CI comprueba que ese puntero siga existiendo y siga
declarando `md5` y `nfiles`.

### Por que por HTTP y no leyendo su base de datos

`GET /api/coco/export` es el contrato publico que el propio README del
Proyecto 1 declara como entregable. Usarlo evita acoplar este proyecto a su
esquema de Drizzle y evita necesitar sus credenciales de MariaDB o MinIO. La
llave que une las dos mitades es el `id`: el de `coco.images[]` es el mismo que
el de `GET /api/images/{id}/file`.

### Por que la descarga vive fuera del pipeline

Ocurre **una vez**. El pipeline solo lee `data/raw/`, asi que sigue siendo
reproducible aunque el Proyecto 1 no este corriendo — que es exactamente la
situacion del evaluador. Una etapa que hiciera una peticion HTTP dejaria de ser
determinista.

### Sobre el conteo

Se cuentan **imagenes distintas que contienen al menos una caja de esa clase**,
no cajas: una foto con siete coches aporta una imagen a `car`, no siete. Y es
un conteo *antes* de colapsar casi-duplicados; el numero que vale para la
evaluacion es el de despues, que dara el analizador de duplicados.


## Ingerir el dataset (Tier 1)

Una vez los datos estan en `data/raw/`, este comando los reparte entre los dos
almacenes:

```bash
dq ingest
```

```
data/raw/annotations.coco.json ──► CocoDataset (Pydantic)
                                        │
                      ┌─────────────────┴─────────────────┐
                      ▼                                   ▼
        MinIO: los bytes de cada imagen       MariaDB: metadatos y cajas
        bucket `dataset-images`,              categories / images / annotations
        llave `raw/<archivo>`
```

### Por que las imagenes no van a MariaDB

Los metadatos se consultan y se agregan (*¿cuantas cajas de clase `dog` hay?*);
eso en SQL es una linea. Los binarios solo se guardan y se sirven, y para eso
una base de datos es el peor sitio: meter 877 JPEGs en columnas hace que las
copias de seguridad tarden horas y obliga a pasar cada imagen entera por el
servidor para mostrarla.

El reparto es el estandar: **los metadatos a la base, los bytes al almacen de
objetos**. En `images.storage_key` queda la llave del objeto; el binario nunca
entra en una columna. Hay una prueba que lo verifica (`test_ingest.py`).

En local ese almacen es MinIO; en produccion es S3. El codigo es el mismo — solo
cambia el endpoint.

### Tres propiedades del Tier 1

**Valida antes de escribir.** El COCO pasa entero por los modelos Pydantic del
Frente 2. Un archivo roto se rechaza nombrando el campo:

```
data/raw/annotations.coco.json: 1 error(es) de validacion
  - images.0.width: Input should be greater than 0 (recibido: 0)
```

**Sube antes de registrar.** Los objetos van primero y las filas despues, de
modo que nunca queda una fila apuntando a un objeto que no existe.

**Es idempotente.** Correrlo dos veces deja el mismo estado: las imagenes que ya
estan en MinIO no se vuelven a subir (se comparan por tamano) y las tablas se
redefinen en vez de acumular.

### Verificar

```bash
# filas en MariaDB
docker compose exec mariadb sh -c   'mariadb -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE" -e    "SELECT COUNT(*) FROM images; SELECT COUNT(*) FROM annotations;"'

# objetos en MinIO
docker compose exec minio sh -c   'mc alias set l http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" &&    mc du l/dataset-images'
```


## Generar los splits (Tier 4)

Una vez el dataset esta en `data/raw/` y la compuerta de calidad (Tier 3) pasa,
este comando reparte las imagenes en train/val/test:

```bash
dq gate     # Tier 3 — tiene que pasar antes
dq split    # Tier 4 — splits.json
```

```
reports/quality.json ──► ¿status == pass? ──► CocoDataset + pHash (Frente 3)
                                                        │
                                          agrupa casi-duplicados en unidades
                                                        │
                                       reparte por estrato (semilla + largest
                                       remainder) ──► reports/splits.json
```

### Por que la compuerta bloquea a `dq split`

`quality.json` en `fail` significa que la compuerta del Tier 3 detecto algo
que no debe publicarse (por ejemplo, demasiados duplicados). Generar splits
sobre ese dataset produciria un `splits.json` que habria que tirar en cuanto
se arreglara el problema. `dq split` lee `reports/quality.json` y se niega a
correr si no existe o si `status == "fail"`, con el mismo espiritu que el
docstring de la compuerta promete: *"la etapa siguiente del pipeline no se
ejecuta"*. `--force` salta la comprobacion a proposito, dejando constancia en
la terminal — util para iterar en local sin un dataset completo todavia.

### Por que se agrupan los casi-duplicados en vez de descartarlos

La unidad que reparte `dq split` no es la imagen: es el **grupo de
casi-duplicados** que ya detecta el pHash del Frente 3
(`analyzers.duplicates.duplicate_groups`, componentes conexas sobre la
distancia de Hamming). Un grupo entero viaja a un solo split, lo que hace la
fuga estructuralmente imposible en vez de ser un chequeo que alguien podria
olvidar. Descartar las copias en vez de agruparlas era la alternativa mas
simple, pero reduce el dataset y puede tirar el minimo de 300 imagenes por
clase que exige la compuerta M3 — agrupar no pierde ninguna imagen.

### Por que se estratifica por la clase minoritaria de la imagen

Una imagen puede tener cajas de varias clases. Usar la clase **menos
frecuente** de cada imagen como etiqueta de estratificacion (en vez de la mas
frecuente, o de la combinacion completa) protege a las clases raras: son las
que mas se perjudican si quedan mal representadas en val/test, y una clase
con pocas imagenes en todo el dataset no puede permitirse perderlas todas en
train.

### Verificar

```bash
# El artefacto valida contra su propio contrato congelado
python -c "
from pathlib import Path
from dataset_quality.models.splits import SplitsManifest
m = SplitsManifest.model_validate_json(Path('reports/splits.json').read_text())
print(m.counts, 'total:', len(m.assignments))
"

# Reproducibilidad: misma semilla, mismo reparto
dq split --out /tmp/a.json && dq split --out /tmp/b.json
diff <(python -c "import json;d=json.load(open('/tmp/a.json'));d.pop('generated_at');print(d)") \
     <(python -c "import json;d=json.load(open('/tmp/b.json'));d.pop('generated_at');print(d)")
```

## Versionar y publicar (Tier 5, Frente 6)

Con la compuerta en `pass` y los splits generados, `dq release` empaqueta el
dataset y sus dos reportes en un artefacto inmutable, lo sube al almacen de
objetos y registra la version:

```bash
dq gate && dq split   # tienen que pasar antes
dq release            # Tier 5 — versions.json + s3://dataset-releases/...
```

```
quality.json + splits.json + annotations.coco.json
                    │
      tar + zstandard, metadata deterministica
      (mtime fijo, orden fijo de miembros)
                    │
                    ▼
      s3://dataset-releases/<version>/dataset.tar.zst
                    │
                    ▼
              reports/versions.json  (registro acumulado)
```

### El pipeline por etapas: `dvc.yaml`

Las cuatro etapas puras del pipeline — `analyze`, `gate`, `split`, `release` —
estan declaradas en `dvc.yaml` con sus `deps`/`outs` exactos, para que
`dvc repro` reejecute solo lo que cambio:

```bash
dvc dag       # dibuja el grafo: gate -> split -> release (analyze es aparte)
dvc repro     # corre lo que haga falta; si nada cambio, no hace nada
```

`gate` depende de `data/raw/` y `quality.yaml`; `split` depende ademas de
`reports/quality.json`, así que **DVC no genera splits si la compuerta no
paso** — el mismo candado que ya aplica `dq split` por su cuenta, ahora
tambien expresado en el grafo. `release` depende de `quality.json` y
`splits.json`.

### Por que `dq ingest` no es una etapa de `dvc.yaml`

`dvc repro` tiene que ser una funcion determinista de archivos a archivos.
La ingesta escribe en MinIO y MariaDB, no deja un artefacto en disco que DVC
pueda cachear, y exigiria Docker levantado para reproducir el pipeline. Queda
como paso manual previo — igual que `export_from_mp1.py`, y por la misma
razon: ocurre una vez, no en cada corrida del pipeline.

### Que va a Git y que no

| Se versiona en Git | Vive solo en el remote (`dvc push`) |
| --- | --- |
| `dvc.yaml`, `dvc.lock` | `data/raw/` (el dataset crudo) |
| `data/raw.dvc` (el puntero: hash del directorio, 112 bytes) | — |
| `reports/*.json` (`cache: false`: texto pequeño y diferenciable) | `reports/releases/<version>/dataset.tar.zst` |
| `.dvc/config` (URLs de los remotes, sin credenciales) | — |
| `.dvc/config.local` **nunca** — esta en `.dvc/.gitignore` | credenciales de `dev`/`prod` |

### Recuperar el dataset evaluado en un clon limpio

El dataset **no está en Git** a propósito: son 634 MB de imágenes. Lo que Git
versiona es el puntero `data/raw.dvc` (112 bytes) con el hash del directorio
completo. Un clon recién hecho tiene el puntero y no las imágenes, y este es el
comando que las trae:

```bash
# --- Opción A: desde el remote DEV (MinIO local) ---
python scripts/up.py              # levanta MinIO
python scripts/dvc_remote.py      # escribe .dvc/config.local desde .env
dvc pull -r dev data/raw.dvc

# --- Opción B: desde el remote PROD (S3 real) ---
# Necesita un perfil AWS autorizado; el nombre del perfil es lo ÚNICO que se
# guarda en local, nunca las llaves.
dvc remote modify --local prod profile <perfil>
dvc pull -r prod data/raw.dvc

# Verificar que lo que bajó es exactamente lo evaluado:
dvc status                        # "Data and pipelines are up to date."
```

No hay que confiar en que la descarga sea la correcta: DVC compara el hash de
lo que baja contra `data/raw.dvc` y **falla** si no coincide, en vez de
continuar con un dataset distinto. El `dataset_fingerprint` que aparece en
`reports/quality.json` y en cada versión de `reports/versions.json` es la otra
mitad de la misma garantía.

En el repositorio no hay ninguna credencial pegada para esto: la opción A las
lee de `.env` (que está en `.gitignore`) y la B, de un perfil de `~/.aws`.
`scripts/recalculo_independiente.py` imprime estos mismos comandos si no
encuentra `data/raw/`, para que el error diga qué hacer en vez de reventar con
un rastro de Python.

### Remotes DEV/PROD

`dev` (MinIO local) es el remote por defecto; `prod` (S3 real) esta declarado
pero sin credenciales hasta que exista un bucket de produccion:

```bash
cat .dvc/config                   # solo URLs y region, versionado, sin secretos
python scripts/dvc_remote.py      # escribe .dvc/config.local desde .env (MinIO)
dvc push data/raw.dvc             # sube al remote activo (dev)
dvc push -r prod data/raw.dvc     # y al bucket de S3
```

Las credenciales de `prod` **no** viven en el repositorio, ni siquiera en un
archivo ignorado: `.dvc/config.local` solo guarda el NOMBRE de un perfil de
`~/.aws` (`dvc remote modify --local prod profile <perfil>`), y DVC resuelve
las llaves desde ahi. En CI no hay perfil ni llaves: el workflow asume un rol
por OIDC y DVC toma las credenciales temporales del entorno.

El mismo dataset da el mismo `dataset_fingerprint` sin importar a que remote
se suba: el archivo se arma con metadata deterministica (mtime fijo a epoca
0, miembros en orden fijo), asi que el contenido —no el destino— es lo unico
que determina el hash.

### Comparar y promover releases

Cada release nuevo conserva `quality_summary`: imagenes distintas por clase
tras colapsar duplicados y proporcion de objetos pequenos. La pantalla Versions
compara las dos ultimas versiones contra el mismo requisito de 300 imagenes,
lista las clases que cruzan el minimo y muestra el cambio de objetos pequenos
en puntos porcentuales. No consulta los reportes vigentes para describir una
version antigua.

Para recuperar el resumen de `0.1.1`, que esta contenido en la exportacion
actual, el siguiente comando verifica primero que el dataset historico tenga
exactamente la huella registrada. Recalcula objetos pequenos con la politica
vigente, usando la misma definicion en ambas versiones:

```bash
python scripts/backfill_version_quality.py 0.1.1
```

La promocion conserva version, fecha y huellas, y copia el archivo de DEV al
bucket `dataset-quality-releases-750702272375`. Usa credenciales AWS independientes de
MinIO: un perfil explicito en el host o el rol OIDC del repositorio en Actions.

```bash
dq promote 0.1.3 --remote prod --profile <perfil-autorizado>
# Validar una copia local sin acceder a AWS ni modificar el manifiesto:
dq promote 0.1.3 --archive reports/releases/0.1.3/dataset.tar.zst --dry-run
# Registrar en DVC la metadata de promocion despues de verificar PROD:
dvc commit --force release
dvc status
```

`--archive` acepta una copia local cuyo contenido y SHA-256 coinciden con la
version publicada. La promocion exige calidad en `pass`, al menos dos clases
con 300 imagenes distintas y el check del minimo activo con severidad `error`.
No sobrescribe archivos distintos bajo la misma version; repetir una
promocion identica verifica la copia y no duplica `published_in`.

CI llama al workflow reutilizable `promote-dataset.yml` solo desde la rama
`main`, mediante `vars.AWS_ROLE_ARN`, despues de validar Python, web y
Terraform. Primero intenta recuperar el puntero vigente de PROD; si su cache
aun no esta publicado, recupera el puntero anterior. Normaliza el COCO y
verifica que tanto el puntero nuevo como el archivo sean identicos a los
validados localmente antes de subirlos. Si PROD no contiene ese dataset,
aborta sin publicar otro. El job `versionado` espera a la promocion antes de
ejecutar `dvc pull` y la compuerta sobre una descarga limpia desde PROD.
Guarda el resultado y el enlace de ejecucion en `reports/prod-promotion.json`.

### Numeracion de versiones

`dq release` sube el patch de la ultima version publicada (`0.1.0 -> 0.1.1`);
`--minor`/`--major` suben esa parte, y `--version X.Y.Z` fuerza un valor.
Sin historial previo arranca en `0.1.0`.

### Verificar

```bash
# El registro valida contra su propio contrato congelado
python -c "
from pathlib import Path
from dataset_quality.models.versions import VersionsManifest
m = VersionsManifest.model_validate_json(Path('reports/versions.json').read_text())
last = m.versions[-1]
print(last.version, last.storage_uri, last.quality_status)
"

# El release esta de verdad en el bucket
docker compose exec minio sh -c \
  'mc alias set l http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" && mc ls -r l/dataset-releases'

# Reproducibilidad del grafo: sin cambios, dvc no reejecuta nada
dvc repro     # "Stage ... didn't change, skipping"

# --dry-run arma el archivo y calcula sus huellas sin subir nada
dq release --dry-run
```

## Verificación

| Comando | Qué verifica |
| ------- | ------------ |
| `python scripts/check.py` (o `make check`) | **Validación diaria (<30s, Frente 10)**: Ruff lint + format, pytest, Terraform validate e higiene de Git/secretos en un solo paso. |
| `python scripts/up.py` | App + MariaDB + MinIO arriba, buckets creados y `/health` en OK. |
| `curl localhost:8000/health` | `200` con ambos checks en `up`; `503` si alguno está caído. |
| `curl localhost:8000/api/config` | Configuración efectiva sin credenciales. |
| `curl localhost:8000/api/policy` | Los umbrales vigentes de `quality.yaml`, tal como los lee la compuerta. |
| `pytest` | Suite completa (configuración y health). |
| `ruff check . && ruff format --check .` | Lint y formato en cero. |
| `python scripts/evidencia_dvc.py` | **Reproducibilidad**: dos `dvc repro` seguidos sin que la segunda rehaga nada, y el cache en sincronía con DEV y PROD. Con `--etapas analyze gate split` se limita a las etapas deterministas (lo que usa CI, que no tiene credenciales para `release`). |
| `python scripts/recalculo_independiente.py` | **Que los números son ciertos**: recalcula las métricas desde el COCO crudo sin usar `dataset_quality`, y las contrasta con `reports/*.json`. |
| `pytest tests/test_mutaciones.py` | **Que los analizadores detectan**: cuatro defectos inyectados a propósito, cada uno con su código de salida. |
| `python scripts/lock_requirements.py --check` | El lockfile de Python corresponde a `pyproject.toml`. |
| `cd web && npx playwright test` | Las siete pantallas, el hover/filtro de la PCA y la persistencia de Settings, contra la app levantada. |

### Finales de línea: por qué `dvc.lock` dejó de ser portable

Merece su propia sección porque es un fallo invisible y costó un CI en rojo.

Los `reports/*.json` son salidas de etapa declaradas con `cache: false`, así que
viajan por Git. Con `core.autocrlf=true` —el valor por defecto de Git para
Windows— el checkout los escribe con **CRLF**, y en Linux quedan con **LF**.
Hasta ahí, inofensivo: el JSON es el mismo y cualquier lector lo interpreta
igual. Pero **DVC no lee, hashea bytes**. Dos finales de línea distintos son dos
md5 distintos.

La consecuencia: un `dvc repro` corrido en Windows grababa en `dvc.lock` los
hashes de la versión CRLF. En CI, que es Linux, esos mismos archivos tenían LF,
ningún hash coincidía, las cuatro etapas salían como `modified` y `dvc repro`
reejecutaba el pipeline entero — justo lo contrario de lo que el lock existe
para garantizar.

El arreglo tiene dos mitades, y hacen falta las dos:

| Mitad | Dónde | Qué evita |
| --- | --- | --- |
| `newline="\n"` en cada escritor de artefactos | `tiers/gate.py`, `splits.py`, `release.py`, `pipeline.py`, `dedupe.py`, `cli.py` | Que el **pipeline** produzca CRLF al correr en Windows |
| `eol=lf` | `.gitattributes` (raíz del repo) | Que el **checkout de Git** reintroduzca CRLF |

`tests/test_finales_de_linea.py` lo vigila por los dos lados: que cada escritor
emita LF, y que los `reports/*.json` del repositorio no tengan ni un CRLF.

Tras clonar o cambiar `.gitattributes`, renormaliza una vez:

```bash
git add --renormalize .
```

Nota: `data/raw/annotations.coco.json` **no** entra aquí. No está en Git — lo
gestiona DVC — y los bytes que hay en el cache de `dev`/`prod` son los
canónicos, sean los que sean. Tocarlo cambiaría `data/raw.dvc` y obligaría a
volver a subir 634 MB a los dos remotes sin ganar nada.

### Evidencia de reproducibilidad

`dvc.lock` puede estar versionado y ser mentira: basta con que alguien regenere
un reporte a mano después de la última corrida. Lo único que lo demuestra es
correr el pipeline dos veces y exigir que la segunda no ejecute ninguna etapa.

```bash
python scripts/evidencia_dvc.py
# -> reports/evaluation/dvc-reproducibilidad.{md,json}
```

Sale con código `!= 0` si la segunda corrida rehace algo, si los hashes de
`dvc.lock` se mueven entre corridas, o si el cache local no coincide con alguno
de los dos remotes. Con `--sin-remotes` se salta `dvc status -r dev/prod`
(necesitan MinIO levantado y un perfil AWS).

### Recálculo independiente de las métricas

`reports/quality.json` lo escribe el mismo código que decide si el dataset está
bien, así que por sí solo no prueba nada: un error en un analizador se hereda al
reporte y nada lo delata. `scripts/recalculo_independiente.py` es un segundo
programa que parte del dato crudo y **no importa `dataset_quality`** — ni
siquiera `imagehash`: el pHash está reimplementado sobre numpy, porque usar la
misma librería reproduciría un mal uso en vez de detectarlo.

```bash
python scripts/recalculo_independiente.py
# -> reports/evaluation/recalculo.{md,json}, tabla reportado contra recalculado
python scripts/recalculo_independiente.py --sin-imagenes   # salta el pHash de las 2045
```

Compara cajas por clase, imágenes por clase, objetos pequeños (ratio, conteo,
ids y desglose), duplicados (pares y copias), sesgo espacial, cajas degeneradas
y desbalance. Sale con código `!= 0` si cualquiera diverge. De paso comprueba
algo que el pipeline no mira: si el campo `area` de cada anotación COCO coincide
con el `ancho*alto` de su `bbox`.

### Pruebas de mutación

El recálculo confirma que los números coinciden, pero en este dataset varios
checks dan cero — y coincidir en un cero no prueba que el detector funcione.
`tests/test_mutaciones.py` cubre esa otra mitad: parte de un dataset que la
compuerta aprueba e inyecta **un** defecto cada vez.

| Mutación | Qué tiene que pasar |
| --- | --- |
| Copia recomprimida de una foto (otro md5, misma imagen) | `duplicates` la marca como copia y la compuerta sale con `!= 0` |
| `bbox` con coordenada negativa | El COCO se rechaza al leerlo, nombrando la anotación; no se escribe `quality.json` |
| `bbox` que se sale del borde de su imagen | `degenerate_boxes` la reporta y la compuerta sale con `!= 0` |
| `min_images_per_class` inalcanzable | La compuerta bloquea contra el umbral configurado |

La política de las pruebas es la **real**: se lee `quality.yaml` y solo se baja
`min_images`, porque exigir 300 imágenes haría fallar a las cuatro por un motivo
que no es el suyo. Si alguien afloja `phash_hamming_distance` en el archivo del
proyecto, la primera mutación deja de detectarse y la suite se pone en rojo.

### Comprobar que la validación de secretos funciona

```bash
grep -v '^DB_PASSWORD=' .env > .env.tmp && mv .env .env.bak && mv .env.tmp .env
docker compose config          # debe fallar nombrando DB_PASSWORD
mv .env.bak .env               # restaurar
```

## Desarrollo en el host (opcional)

Para ejecutar pruebas y linter fuera de Docker:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux / macOS

# Desde el lockfile: las versiones EXACTAS que usan CI y la imagen.
pip install -r requirements.lock.txt
pip install --no-deps -e .

pytest
ruff check . && ruff format .
```

Las pruebas no tocan Docker ni la red: `tests/conftest.py` inyecta un entorno
completo y `/health` se prueba con dobles de las dependencias.

### Por qué hay lockfile además de `pyproject.toml`

`pyproject.toml` declara **rangos** (`fastapi>=0.115`), que es lo correcto para
una librería y lo peor posible para reproducir un entorno: `pip install -e .`
hoy y dentro de un mes traen árboles distintos sin que nadie haya tocado el
repositorio, y un build que se rompe así parece un fallo del código.
`requirements.lock.txt` congela las 153 dependencias — directas y transitivas —
con su versión exacta.

El `--no-deps` del segundo comando no es adorno: sin él, `pip` vuelve a resolver
los rangos de `pyproject.toml` y deshace los pines que acaba de instalar.

Se regenera con un solo comando, y **siempre dentro de `python:3.12-slim`** — la
misma imagen del `Dockerfile` y del runner de CI. Un `pip freeze` desde un venv
de Windows no sirve: la resolución depende de la plataforma, arrastraría
paquetes que en Linux no existen y omitiría los que solo existen allí.

```bash
python scripts/lock_requirements.py            # regenera (necesita Docker)
python scripts/lock_requirements.py --check    # falla si está desactualizado; lo corre CI
```

`dvc` entra por el extra `pipeline` y ya está dentro del lockfile, así que tanto
el host como la imagen lo tienen: eso es lo que permite verificar la
reproducibilidad del pipeline en el mismo entorno que se evalúa.

## Pruebas de navegador (Frente 7)

`web/tests/e2e/` corre con Playwright **contra la app levantada**, no contra
mocks. Tiene un coste — hay que levantar el entorno primero — y a cambio lo que
se comprueba es lo que se entrega: que las siete pantallas piden sus artefactos
al backend y los reciben con `200`, que la proyección responde al ratón y que
guardar la política la escribe de verdad en `quality.yaml`.

```bash
python scripts/up.py                  # la app tiene que estar arriba
cd web
npm ci
npx playwright install --with-deps chromium
npx playwright test                   # -> reports/evaluation/playwright/
npm run test:e2e:report               # abre el reporte con las capturas
```

Sin el dataset en disco —un clon sin acceso al remote de DVC, o CI— falta una
pieza: el hover de la PCA pide `GET /api/exploration/thumbnail/{id}`, que abre
la imagen real de `data/raw/images/`, y sin ella el endpoint responde `404` con
toda la razón. Para ese caso:

```bash
python scripts/imagenes_de_prueba.py  # un JPEG diminuto por cada file_name
```

Escribe un archivo por cada `file_name` del manifiesto versionado y **nunca
sobrescribe** uno que ya esté, así que correrlo sobre el dataset real no toca
ninguna foto. El endpoint sigue haciendo su trabajo entero —resolver el id
contra el manifiesto, abrir, redimensionar y codificar— solo que sobre imágenes
de relleno: lo único que deja de probarse es qué se ve en la miniatura.

Cubre las siete pantallas (una por una, con captura adjunta y la verificación de
que ninguna respuesta de `/api/` salió distinta de `200`), el hover de la PCA
—que aparezca la miniatura y que el backend la sirva— el filtro de la leyenda
—que aísle una clase y que «todas» lo deshaga— y la persistencia de Settings.

Un aviso sobre esa última: **la suite de Settings escribe en `quality.yaml`**,
que es el archivo que lee `dq gate`. Guarda la política original antes de tocar
nada y la repone en un `afterAll` incondicional; CI comprueba además que el
árbol quedó limpio. Es la única forma de probar persistencia de verdad: que el
valor siga ahí después de recargar el navegador, no que el estado de React
cambió.

## Integración continua

`.github/workflows/ci.yml` corre en cada push y **falla el build** si algo no
cumple. Ningún job lleva `continue-on-error`.

| Job | Qué comprueba |
| --- | --- |
| **Ruff + pytest** | Lint, formato y la suite completa, instalando desde el lockfile. Vuelve a invocar las mutaciones y las pruebas del Copilot por su nombre, para que borrarlas rompa el build en vez de reducir la suite en silencio. |
| **El lockfile está al día** | Reresuelve `pyproject.toml` desde cero y exige que dé byte a byte el `requirements.lock.txt` commiteado. |
| **Arranque desde cero + navegador** | `python scripts/up.py` en un runner limpio (la comprobación que hace el evaluador al clonar) y, encima, las pruebas de Playwright contra esa app. Publica el reporte con capturas como artefacto y verifica que `quality.yaml` quedó intacto. |
| **La compuerta bloquea el build** | Prepara un dataset que no llega al mínimo y exige que `dq gate` salga con `!= 0` y nombre la regla. Sin esto, el `exit 1` de la compuerta solo existiría en la terminal de quien lo corre a mano. |
| **Terraform Validate** | `fmt -check`, `init -backend=false` y `validate`. |
| **El dataset sigue versionado** | Con el rol OIDC: `dvc pull -r prod`, la compuerta sobre esa descarga limpia, el recálculo independiente y las dos corridas de `dvc repro`. Publica `reports/evaluation/` como artefacto. |

### Conectar el rol OIDC (paso manual, una vez)

Terraform ya crea el rol y la confianza con GitHub
(`terraform/modules/oidc_github`). Lo que falta es decirle al repositorio cuál
es, y eso no se puede versionar: es una variable de GitHub.

```bash
gh variable set AWS_ROLE_ARN \
  --body "$(terraform -chdir=Proyecto2/terraform output -raw github_actions_role_arn)"
```

Va en `vars` y no en `secrets` a propósito: un ARN no es material sensible, y la
compuerta M2 exige cero llaves de larga vida en el repositorio. La trust policy
del rol solo acepta `repo:<owner>/<repo>:*`, así que un fork no puede asumirlo
aunque conozca el ARN.

**Mientras la variable no exista, el job `versionado` falla en `main`** en vez
de saltarse los pasos en silencio — que era el modo de fallo peligroso: un job
en verde que no verificó nada contra PROD porque le faltaba una variable que
nadie miró. En forks y en ramas de trabajo sigue siendo un salto legítimo.

---

## Estructura

```
.
├── docker-compose.yml          # app + MariaDB + MinIO + minio-init
├── docker/Dockerfile           # imagen de la app (python:3.12-slim, usuario no root)
├── .env.example                # plantilla: el ÚNICO lugar con credenciales
├── .github/workflows/ci.yml    # lint, pruebas, arranque desde cero y grafo de DVC
├── dvc.yaml                     # pipeline por etapas (Frente 6): analyze, gate, split, release
├── dvc.lock                      # hashes de deps/outs de cada etapa — se versiona en Git
├── .dvc/config                   # URLs de los remotes dev (MinIO) y prod (S3); sin credenciales
├── requirements.lock.txt         # las 153 dependencias con su version exacta (resuelto en Linux)
├── scripts/
│   ├── up.py                   # el comando: levanta y verifica todo
│   ├── down.py                  # apaga el entorno
│   ├── dvc_remote.py             # escribe .dvc/config.local (credenciales) desde .env
│   ├── lock_requirements.py      # regenera el lockfile dentro de python:3.12-slim
│   ├── evidencia_dvc.py          # dos `dvc repro` + estado de los remotes -> reports/evaluation/
│   └── recalculo_independiente.py # recalcula las metricas SIN importar dataset_quality
├── quality.yaml                 # umbrales de calidad (Frente 4) y parametros de splits (Frente 5)
├── src/dataset_quality/
│   ├── settings.py             # pydantic-settings: la frontera con el entorno
│   ├── db.py                   # engine SQLAlchemy -> MariaDB
│   ├── storage.py              # cliente S3 -> MinIO
│   ├── tables.py                # tablas SQLAlchemy: images, annotations, categories, splits, dataset_versions
│   ├── cli.py                   # subcomandos `dq`: ingest, analyze, gate, split, release, init-db
│   ├── main.py                  # FastAPI: /, /health, /api/config, /api/policy, /docs
│   ├── policy.py                # reescribe quality.yaml sin perder sus comentarios
│   ├── analyzers/                # Frente 3: los cinco analizadores + descriptiva
│   │   └── duplicates.py        # pHash, distancia de Hamming, grupos de casi-duplicados
│   ├── tiers/                    # un modulo por etapa del pipeline
│   │   ├── ingest.py             # Tier 1 — COCO -> MinIO + MariaDB (fuera del grafo DVC)
│   │   ├── gate.py               # Tier 3 — compuerta de calidad -> quality.json
│   │   ├── splits.py             # Tier 4 — splits estratificados -> splits.json
│   │   └── release.py            # Tier 5 — empaqueta y publica -> versions.json (Frente 6)
│   ├── models/                 # Pydantic v2: COCO, quality.yaml y los 3 contratos de salida
│   │   ├── coco.py             # dataset COCO crudo (entrada)
│   │   ├── quality.py          # quality.yaml (entrada) y quality.json (salida)
│   │   ├── splits.py           # splits.json (salida, contrato congelado)
│   │   ├── versions.py         # versions.json (salida, contrato congelado)
│   │   └── errors.py           # ValidationError -> mensaje que nombra el campo
│   └── static/index.html       # landing con el estado de la infraestructura
├── tests/                      # pytest
│   ├── test_mutaciones.py        # inyecta 4 defectos y exige que la compuerta los vea
│   ├── test_copilot_resiliencia.py # fuente modificada, pregunta no respondible, proveedor caido
│   └── fixtures/                # ejemplos COCO y los 3 golden files congelados
├── web/
│   ├── playwright.config.ts      # pruebas de navegador contra la app levantada
│   └── tests/e2e/                # las 7 pantallas, hover/filtro de la PCA, Settings
└── reports/evaluation/           # evidencia generada por comando (ver su README)
```

## Contratos de datos (Frente 2)

Los modelos de `src/dataset_quality/models/` son la frontera tipada del proyecto:
todo lo que entra o sale de la plataforma de calidad se valida contra ellos, y
un documento inválido se rechaza nombrando el campo exacto que falló (no un
traceback genérico de Pydantic).

| Archivo | Dirección | Modelo principal |
| --- | --- | --- |
| dataset COCO crudo | entrada | `models.coco.CocoDataset` |
| `quality.yaml` | entrada | `models.quality.QualityConfig` |
| `quality.json` | salida — **contrato congelado** | `models.quality.QualityReport` |
| `splits.json` | salida — **contrato congelado** | `models.splits.SplitsManifest` |
| `versions.json` | salida — **contrato congelado** | `models.versions.VersionsManifest` |

Los tres contratos de salida están en `schema_version=1` y protegidos por
`tests/test_contratos_congelados.py`, que hace un round-trip contra los
ejemplos de oro en `tests/fixtures/`. Cambiar su forma sin subir la versión y
actualizar esos fixtures rompe la prueba a propósito: es lo que permite que
los Frentes 3, 4, 5, 7 y 8 desarrollen en paralelo contra un contrato estable.

### El detalle de duplicados dentro de `quality.json`

`CheckResult` lleva un campo opcional `duplicates` que **solo rellena el check
del mismo nombre**; en los demás es `null`. Es un añadido compatible hacia
atrás —un `quality.json` escrito antes de que existiera sigue validando— así
que `schema_version` sigue en 1.

```json
"duplicates": {
  "max_distance": 5,
  "pairs": [{"kept": 1, "duplicate": 40, "distance": 0, "similarity": 1.0}],
  "groups": 1,
  "images_by_class": {"car": 1, "person": 1},
  "boxes_by_class": {"person": 3, "car": 1},
  "images_without_class": 0
}
```

El analizador ya calculaba los pares para decidir el veredicto y los tiraba: lo
único que sobrevivía era la lista de ids sobrantes. Con eso no se puede
responder *cuántos duplicados hay y a qué clase afectan* sin volver a abrir
todas las imágenes, que es la parte cara. Ahora el dato viaja en el reporte,
que es lo que leen la pantalla de Analyzers y las herramientas del Copilot.

`images_by_class` cuenta imágenes **sobrantes** que contienen al menos una caja
de esa clase, ordenadas de mayor a menor. Una copia con cajas de dos clases
suma en las dos, así que la suma puede superar el número de copias: es
exactamente lo que hay que restarle a cada clase para saber con cuántas
imágenes distintas se queda de verdad (la cuenta de la compuerta M3).

### Editar la política desde la app: `/api/policy`

| Endpoint | Qué hace |
| --- | --- |
| `GET /api/policy` | La política vigente, leída de `quality.yaml` y validada con `QualityConfig`. |
| `PUT /api/policy` | La reescribe. El cuerpo es un `QualityConfig` completo: un umbral fuera de rango se rechaza con 422 nombrando el campo, antes de tocar el disco. |

La escritura **no** hace `yaml.safe_dump` del modelo entero: eso borraría los
comentarios de `quality.yaml`, que son los que explican por qué `min_images`
son 300 y no 50. `src/dataset_quality/policy.py` reescribe solo las líneas cuyo
valor cambia, así que el diff de Git enseña qué umbral se movió y a qué valor.
Lo escrito se vuelve a leer y validar antes de reemplazar el archivo: si el
texto reescrito no produce exactamente la política pedida, no se guarda nada.

Cambiar la política no vuelve a medir el dataset. La respuesta lo dice
(`stale_reports`) y la pantalla ofrece el botón de recalcular al lado.


## Estado y siguiente paso

**Frente 1 (Arquitectura y entorno) — cerrado.** Un comando levanta app +
MariaDB + MinIO, la configuración va por pydantic-settings y no hay ninguna
credencial en el código.

**Frente 2 (Validación Pydantic) — cerrado.** Modelos Pydantic v2 del COCO, de
`quality.yaml` y los tres contratos de salida (`quality.json`, `splits.json`,
`versions.json`) congelados con ejemplos escritos a mano.

**Frente 3 (Analizadores de calidad) — cerrado.** Los cinco analizadores
(objetos pequeños, desbalance de clases, duplicados por pHash, cajas
degeneradas, sesgo espacial) corren sobre `CocoDataset` y devuelven
`CheckResult`; `dq analyze` los orquesta.

**Frente 4 (Compuerta de calidad) — cerrado.** `dq gate` evalúa la política de
`quality.yaml`, escribe `quality.json` y **devuelve el exit code real**: un
`fail` con `severity=error` detiene el pipeline de verdad.

**Frente 5 (Splits estratificados) — cerrado.** `dq split` reparte
train/val/test estratificando por la clase minoritaria de cada imagen, agrupa
los casi-duplicados del pHash (Frente 3) en una sola unidad para garantizar
cero fuga, reparte por semilla con *largest remainder*, y se niega a correr
si la compuerta de calidad (Frente 4) está en `fail` — salvo `--force`.

**Frente 6 (Versionado con DVC) — cerrado.** `dvc.yaml` declara el pipeline
por etapas (`analyze`, `gate`, `split`, `release`); `dq release` empaqueta el
dataset y sus reportes en un `.tar.zst` determinístico, lo publica en
`s3://dataset-releases/<version>/` y registra la entrada en `versions.json`
— el tercer contrato congelado, ya con productor. Dos remotes (`dev` hacia
MinIO local, `prod` hacia S3) comparten el mismo content hash sin importar
a cuál se suba.

**Frente 7 (App web) — cerrado.** La SPA presenta los artefactos validados y
las acciones disponibles del pipeline.

**Frente 8 (Dataset Copilot MCP) — cerrado.** Un sidecar interno de lectura
expone cinco herramientas sobre reportes validados; la API orquesta sus
llamadas, las audita y muestra evidencia versionada bajo cada respuesta.

**Frente 9 (Infraestructura — Terraform) — cerrado.** 3 módulos por capa:
red con VPC Endpoint para S3, almacenamiento S3 versionado con SSE-S3 y
bloqueo público, e IAM OIDC sin claves estáticas para GitHub Actions.
Validación automática integrada en CI.

**Frente 10 (Ruff, pytest y CI) — cerrado.** Lint en cero (`ruff check`),
formato estricto (`ruff format`), suite de pruebas con verificación de
mutación (Red→Green) y comando único de validación rápida en menos de 5
segundos (`scripts/check.py` / `make check`). Pipeline de CI fail-fast sin
`continue-on-error`.


Lo que sigue, en el orden en que desbloquea:

1. **Migraciones** — Alembic para versionar el esquema de `tables.py`
   (`quality_reports` y `check_results` siguen sin tabla; `splits` y
   `dataset_versions` ya existen).
