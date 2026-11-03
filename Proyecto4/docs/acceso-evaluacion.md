# Acceso de evaluación y configuración sin secretos (INT-07)

Cómo accede el evaluador al portal y a AWS sin recibir llaves, y dónde está cada valor configurable. Ningún secreto vive en el repositorio ni en el paquete de evidencias.

## Qué ve el evaluador

| Recurso | Cómo accede | Qué puede hacer |
|---|---|---|
| Portal (P1–P3 + Capturas Edge): **https://54-80-197-58.sslip.io** → menú **Capturas Edge** (`#/capturas-edge`) | Usuario `evaluador` y contraseña entregada por canal privado | Ver todas las páginas, fotos y la exportación CSV/JSON. No puede enviar capturas: `POST /api/p4/capturas` exige el token del dispositivo |
| MLflow: https://mlflow.54-80-197-58.sslip.io | El mismo usuario | Ver corridas |
| AWS (S3) | **El equipo ejecuta la consulta de solo lectura en vivo** durante la demostración (abajo) | Ver cada captura en S3, su versión, fecha y SHA-256. Nunca recibe llaves |

La contraseña se genera en la instancia y se guarda cifrada en Parameter Store (`/p4/portal-evaluador`). Solo un integrante con acceso a la cuenta la lee, desde su terminal:

```bash
aws ssm get-parameter --name /p4/portal-evaluador --with-decryption --query Parameter.Value --output text --profile p4-equipo --region us-east-1
```

## Consulta de solo lectura en AWS (demostración)

**Perfil:** las consultas de esta sección se hacen con `p4-lectura`, el usuario de solo lectura (ver abajo): quien repita la demostración no puede escribir ni borrar por error. `p4-equipo` (administración) se usa solo para leer secretos de Parameter Store y operar la EC2, que `p4-lectura` no puede hacer a propósito.

[`scripts/consultar_captura.py`](../scripts/consultar_captura.py) sigue una captura elegida por el evaluador. Solo usa `sts get-caller-identity`, `get-object` y `list-object-versions`; no escribe ni borra.

```bash
python Proyecto4/scripts/consultar_captura.py <capture_id> --profile p4-lectura
```

Muestra:

1. **Quién consulta:** la identidad que hace la consulta.
2. **El registro:** `edge-capturas/eventos/<id>.json`, con su `VersionId`, la fecha que asignó S3 y los campos del evento.
3. **La foto:** `edge-capturas/fotos/<id>.jpg`, con su `VersionId` y el SHA-256 guardado en sus metadatos.
4. **La comprobación de la foto:** el SHA-256 recalculado de la foto descargada, comparado con el de S3 y con el `image_sha256` del evento.
5. **La comprobación de duplicados:** cuántas versiones tiene cada objeto. Una sola versión significa que nunca se sobrescribió y que no hubo duplicados.

6. **Contra el dispositivo** (opcional): con `--evento-local <id>.json --foto-local <id>.jpg`, copias del registro local de la Raspberry, compara los 11 campos del contrato y el SHA-256 de la foto con lo que guardó S3. Los campos propios del dispositivo (`estado`, `width`…) no se comparan. Así se demuestra que la captura que llegó a AWS es la que generó el dispositivo (INT-04, INT-06):

   ```bash
   python Proyecto4/scripts/consultar_captura.py <capture_id> --profile p4-lectura --evento-local <id>.json --foto-local <id>.jpg
   ```

Si todo coincide termina en `Resultado: OK`. Se probó el 15 de octubre contra el bucket real con una captura de prueba escrita por el receptor (después borrada). Esa captura reusaba el ID de una prueba anterior, y el paso 5 lo detectó y marcó `REVISAR`, como debe.

Comandos equivalentes con la CLI, si se prefiere no usar el script:

```bash
aws s3api head-object --bucket p4-capturas-474665692638 --key edge-capturas/eventos/<id>.json --profile p4-lectura --region us-east-1
```

```bash
aws s3api list-object-versions --bucket p4-capturas-474665692638 --prefix edge-capturas/eventos/<id>.json --profile p4-lectura --region us-east-1
```

## Usuario de solo lectura para la demostración (`p4-lectura`)

Desde el 15 de octubre existe el usuario IAM `p4-lectura`, para hacer la consulta en vivo con una identidad que **no puede escribir ni borrar**.

- **Permisos:** solo [`deploy/politica-evaluador.json`](../deploy/politica-evaluador.json) (leer `edge-capturas/`, `modelos/` y `models/`) y la política de AWS `SignInLocalDevelopmentAccess`, para usar `aws login`. El simulador de IAM confirma escritura, borrado, Parameter Store, EC2 e IAM denegados; un `PutObject` real respondió `AccessDenied`.
- **Credenciales:** sin llaves de acceso. Tiene contraseña de consola, elegida por el equipo y guardada fuera del repo y del chat.
- **Uso:** `aws login --profile p4-lectura` y luego `consultar_captura.py <capture_id> --profile p4-lectura`.
- **Al terminar la evaluación:** se borra el usuario.

## Si el evaluador pide acceso propio a AWS (temporal)

La rúbrica no lo exige: basta la consulta en vivo. Si se pide:

1. **Crear el usuario:** el dueño de la cuenta crea un usuario IAM `p4-evaluador`, **sin acceso a la consola**.
2. **Darle solo lectura:** se le asigna únicamente [`deploy/politica-evaluador.json`](../deploy/politica-evaluador.json). Permite listar y leer `edge-capturas/`, `modelos/` y `models/` (paquete del modelo del P3) del bucket del P4; no permite escribir, borrar ni tocar otros recursos. Está validada con IAM Access Analyzer, sin hallazgos.
3. **Configurar el acceso en la máquina de la demostración:** se crea una llave de acceso y se configura ahí como un perfil aparte. La llave **no se entrega por escrito ni por chat**.
4. **Retirarlo:** al terminar la evaluación, se borran la llave y el usuario.

## Valores configurables (sin secretos en Git)

| Valor | Dónde se configura | En Git |
|---|---|---|
| URL del receptor (dispositivo) | `P4_RECEPTOR_URL` en [`contrato/dispositivo.env.example`](../contrato/dispositivo.env.example) | Sí (no es secreta) |
| Identidad del dispositivo | `P4_DEVICE_ID` en la misma plantilla | Sí |
| Ruta, versión y SHA-256 del modelo en el dispositivo | `P4_MODEL_PATH`, `P4_MODEL_VERSION`, `P4_MODEL_SHA256` | Sí |
| Token del dispositivo | Variable de entorno `P4_TOKEN_DISPOSITIVO` en el dispositivo; en la EC2, `Proyecto2/.env` (generado ahí) y Parameter Store `/p4/token-dispositivo` | **No**: la plantilla lo deja vacío |
| Modelos aceptados por el receptor | `P4_MODELOS_ACEPTADOS` en `Proyecto2/.env` de la instancia | Valor de ejemplo vacío en `Proyecto2/.env.example` |
| Bucket y prefijo de capturas | `P4_BUCKET` y `P4_PREFIJO` | Sí (no son secretos) |
| Credenciales de AWS del portal | **Ninguna**: rol de instancia `p4-portal-ec2` | No existen llaves |
| Contraseña del portal | Hash bcrypt en `/opt/p4/secretos/caddy.env` (solo root) y texto en Parameter Store | **No** |

El CI corre **gitleaks** sobre el repositorio en cada push (job "gitleaks (secretos)" de `p3-ci.yml`). Antes de entregar la carpeta de evidencias (INT-08) se vuelve a revisar que no contenga tokens, contraseñas, llaves ni URLs firmadas.
