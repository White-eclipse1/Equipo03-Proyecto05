# Proyecto 4: modelo del P3 optimizado y clasificación en edge

Ficha de entrega del Equipo 05. El recorrido evaluado:

```
modelo 1.0.0 del P3 → variante INT8 → cámara y clasificación local en el dispositivo
→ foto y metadatos en AWS S3 → sección Capturas Edge del portal de los P1–P3
```

> **Estado al 16 oct de 2026.** ✅ = hecho y con evidencia en el repo. ⏳ = pendiente, con su responsable. Esta ficha se completa conforme se cierran los issues; ningún dato pendiente se rellena sin evidencia.

## Equipo

| Integrante | Rol | Issues |
|---|---|---|
| Diego Lemus (`D-Lemus`) | Cloud, portal e integración de punta a punta | INT-01 a INT-08 |
| Josué (`JGO-07`) | Validación del modelo y benchmark | VAL-01 a VAL-08 |
| Omar (`OmarCTMX`) | Dispositivo edge y cámara | EDGE-01 a EDGE-08 |
| Mauricio Figueroa (`White-eclipse1`) | PM: coordinación, seguimiento y entrega | — |

## Accesos

| Qué | Dónde |
|---|---|
| Portal (P1–P3 + Capturas Edge) | **https://54-80-197-58.sslip.io** → menú **Capturas Edge** (`#/capturas-edge`) |
| Usuario de evaluación | `evaluador`; la contraseña se entrega por canal privado ([acceso de evaluación](docs/acceso-evaluacion.md)) |
| MLflow del P3 | https://mlflow.54-80-197-58.sslip.io (mismo usuario) |
| Receptor del dispositivo | `POST https://54-80-197-58.sslip.io/api/p4/capturas` ([contrato](docs/contrato-capturas.md)) |
| AWS | Cuenta `474665692638`, `us-east-1`, bucket `p4-capturas-474665692638`. El evaluador no recibe llaves: el equipo ejecuta una [consulta de solo lectura](docs/acceso-evaluacion.md#consulta-de-solo-lectura-en-aws-demostración) en vivo |

## Modelo

| Dato | Original (P3) | Variante optimizada (edge) |
|---|---|---|
| Versión | `1.0.0`, run de MLflow `9f9b62c202f0446a8a4b411a10321eff` | `1.0.0-int8-e05.1` |
| Archivo | `model.pt` (PyTorch, ResNet-18) | `model_int8.onnx` (ONNX opset 18) |
| Bytes | 44 783 563 | 11 295 280 (**74.78 % menos**) |
| SHA-256 | `e4acca429ebf73d0e5a60fb0dda383a6a5322dccb1decf04b4e40ab9db989172` | `ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12` |
| En S3 | `models/clasificador/1.0.0/model.pt` y `modelos/clasificador-p3/1.0.0/model.pt` | `modelos/clasificador-edge/1.0.0-int8-e05.1/` |
| Clases (orden de salida) | 0 `cat`, 1 `dog`, 2 `person` | iguales |
| Preprocesamiento | RGB, 224×224 estirado (bilineal), normalización ImageNet | igual, sin PyTorch ([`modelo/preprocesar.py`](modelo/preprocesar.py)) |

**Técnica:** cuantización estática post-entrenamiento con onnxruntime.

- **Formato:** QDQ.
- **Pesos:** INT8 por canal.
- **Activaciones:** UINT8.
- **Calibración:** 300 recortes **solo de train** del manifiesto `m-0.1.3-s42-1`. Validación y test no intervienen.

Detalle en la [ficha del modelo optimizado](docs/modelo-optimizado.md) y en el [registro de conversión](modelo/registros/registro_conversion.json).

**Original contra optimizado** (paquete recalculable de VAL-08: [`evidencias/VAL-08/`](evidencias/VAL-08/), `python recalcular.py` → `VERIFICADO`):

| | Original | INT8 | Cambio |
|---|---:|---:|---:|
| Tamaño | 44 783 563 B | 11 295 280 B | −74.78 % |
| Latencia p50 (preprocesamiento + inferencia) | 190.11 ms | 113.51 ms | −40.29 % |
| Latencia p95 | 191.52 ms | 114.34 ms | −40.30 % |
| Accuracy en `val` (292 muestras) | 99.658 % | 99.315 % | −0.34 pp (límite: 2 pp) |
| F1 macro en `val` | 99.537 % | 99.075 % | |

La latencia son 200 mediciones por modelo tras 10 calentamientos, en la misma Raspberry Pi 4, con el original exportado a ONNX FP32 ([`evidencias/VAL-05/`](evidencias/VAL-05/), [`docs/recursos-edge.md`](docs/recursos-edge.md)). La accuracy del INT8 es la **ejecutada en la Raspberry**, con el preprocesamiento idéntico bit a bit al offline ([`docs/preprocesamiento-edge.md`](docs/preprocesamiento-edge.md), VAL-07).

**Continuidad con el P3 (M1):** [`docs/linaje-modelo.md`](docs/linaje-modelo.md) y [`modelo/registros/linaje_verificacion.json`](modelo/registros/linaje_verificacion.json). Son 20 comprobaciones aprobadas, 0 fallas y 0 pendientes, incluida la verificación de los binarios en S3 (VAL-01).

## Dispositivo

| Dato | Valor |
|---|---|
| Dispositivo | Raspberry Pi 4 Model B Rev 1.5 |
| Cámara | Teléfono POCO C65 con la app IP Webcam 1.19.0.913, conectado a la Raspberry por cable USB |
| Sistema operativo y arquitectura | Debian GNU/Linux 13.7 (Trixie), ARM64 (aarch64), 64 bits |
| Runtime | Python 3.13.5 y onnxruntime 1.31.0 (`CPUExecutionProvider`) |
| Modo de captura | Manual: un disparo por ejecución del comando; imagen completa (`region: null`), JPEG de 1920×1080 |
| `device_id` | `edge01` |
| Modelo en el dispositivo | `/home/pi/edge01/modelo/model_int8.onnx`, SHA-256 `ba89ee43…2a12` verificado en la Raspberry |

Fuente: EDGE-01 (#5, PR #34): [guía del dispositivo](docs/edge-guia.md), [entrega de EDGE-01](docs/edge01-entrega.md) y [`evidencias/EDGE-01/`](evidencias/EDGE-01/) (hardware y runtime, foto nueva de la cámara, hash del modelo y montaje físico).

Configuración del programa del dispositivo, sin secretos: [`contrato/dispositivo.env.example`](contrato/dispositivo.env.example).

## Reproducir

### Conversión del modelo

Desde `Proyecto4/`, con `model.pt` y los recortes del P3 en local. También están en `s3://p4-capturas-474665692638/datos/p3/` y `.../modelos/clasificador-p3/`.

```bash
python -m venv modelo/.venv
modelo/.venv/Scripts/pip install -r modelo/requirements-conversion.lock.txt --extra-index-url https://download.pytorch.org/whl/cpu
modelo/.venv/Scripts/python modelo/convertir.py
```

Dos corridas dan los mismos SHA-256. Para verificar el linaje:

```bash
python modelo/verificar_linaje.py
```

### Portal en local

Desde `Proyecto2/`:

```bash
python scripts/up.py
```

Levanta el portal en http://localhost:8000. Capturas Edge usa el MinIO local; ver la sección Proyecto 4 de `Proyecto2/.env.example`.

### Portal en AWS

Instalación, recursos creados y operación por Session Manager: [`docs/despliegue.md`](docs/despliegue.md). La instancia se crea con [`deploy/instalar_ec2.sh`](deploy/instalar_ec2.sh) como user-data.

### Dispositivo

**Runbook completo** (instalación, cámara, envío, sin red y reinicio): [`docs/edge08-runbook.md`](docs/edge08-runbook.md) (EDGE-08). Hardware y cámara: [`docs/edge-guia.md`](docs/edge-guia.md). Los scripts se copian a `/home/pi/edge01/app/`, porque la Raspberry no usa Git. Son dos programas, que se corren por separado desde `$HOME/edge01` con el entorno activado (`source .venv/bin/activate`):

```bash
# 1. Capturar y clasificar en local (EDGE-05): guarda el JPEG y el evento; no envía
python -u app/eventos.py --modelo modelo/model_int8.onnx --url "http://<ip-del-telefono>:8080/shot.jpg" --cantidad 1 --salida <salida>

# 2. Enviar un evento guardado al portal (EDGE-06): el token se escribe sin mostrarse
read -r -s -p "Token del dispositivo: " P4_TOKEN_DISPOSITIVO; echo; export P4_TOKEN_DISPOSITIVO
python -u app/enviar.py --evento <salida>/eventos/<capture_id>.json --log <salida>/envios.jsonl
```

Detalle por etapa: [captura](docs/edge02-captura.md) (EDGE-02), [inferencia](docs/edge03-inferencia.md) (EDGE-03), [sin red](docs/edge04-offline.md) (EDGE-04), [eventos](docs/edge05-eventos.md) (EDGE-05), [envío](docs/edge06-envio.md) (EDGE-06) y [operación continua y reinicio](docs/edge07-operacion.md) (EDGE-07, `app/operacion.py`).

## Comprobaciones repetibles

| Qué | Comando o archivo | Estado |
|---|---|---|
| Conversión y linaje | `python modelo/verificar_linaje.py` | ✅ |
| Contrato del receptor (5 respuestas) | `python scripts/enviar_prueba.py --profile <perfil>` → [`evidencias/int-02/`](evidencias/int-02/) | ✅ |
| Captura persistida en AWS | `python scripts/consultar_captura.py <capture_id> --profile p4-lectura` → [`evidencias/int-03/`](evidencias/int-03/) | ✅ |
| Falla de envío, reintento y duplicado | [`docs/fallo-reintento.md`](docs/fallo-reintento.md) → [`evidencias/int-04/`](evidencias/int-04/) | ✅ con la Raspberry |
| Una captura del dispositivo hasta S3 y el portal | `consultar_captura.py <capture_id> --profile p4-lectura --evento-local <id>.json --foto-local <id>.jpg` y Capturas Edge → [`evidencias/int-06/`](evidencias/int-06/) | ✅ |
| Capturas Edge con datos de AWS | Portal → Capturas Edge, comparado con la consulta anterior → [`evidencias/int-05/`](evidencias/int-05/) | ✅ con capturas de prueba |
| Benchmark en el dispositivo | `python validacion/verificar_benchmark.py` → [`evidencias/VAL-05/`](evidencias/VAL-05/) | ✅ |
| p50/p95, reducción de tamaño y balance con la calidad | `python validacion/recursos.py` → [`validacion/resultados/recursos_edge.json`](validacion/resultados/recursos_edge.json) | ✅ |
| Pruebas automáticas del receptor | `pytest` en `Proyecto4/` (CI: `p4-ci.yml`) | ✅ |
| Preprocesamiento y entradas conocidas en el dispositivo | `python validacion/contrastar_edge.py` → [`validacion/resultados/contraste_edge.json`](validacion/resultados/contraste_edge.json): tensor idéntico bit a bit en 295 entradas (VAL-07) | ✅ |
| Paquete de calidad y recursos | `python recalcular.py` dentro de [`evidencias/VAL-08/`](evidencias/VAL-08/) → `VERIFICADO` | ✅ |

## Demostración

Guion paso a paso, con roles, comandos y qué hacer si algo falla: [`docs/guion-demo.md`](docs/guion-demo.md).

## Evidencias

Índice completo en [`evidencias/README.md`](evidencias/README.md).
