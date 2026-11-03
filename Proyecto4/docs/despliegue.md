# Despliegue del portal en AWS (INT-01)

El portal de los Proyectos 1 a 3 con la sección **Capturas Edge** corre en una EC2 de la cuenta del equipo, detrás de Caddy con HTTPS. El receptor de capturas guarda en S3 con el **rol de la instancia**: no hay llaves de AWS en archivos, variables ni en el repositorio.

## Dónde está

| Dato | Valor |
|---|---|
| Portal | **https://54-80-197-58.sslip.io** (Capturas Edge en `#/capturas-edge`) |
| MLflow | https://mlflow.54-80-197-58.sslip.io |
| Receptor del dispositivo | `POST https://54-80-197-58.sslip.io/api/p4/capturas` (contrato en [`contrato-capturas.md`](contrato-capturas.md)) |
| Cuenta / región | `474665692638` / `us-east-1` |
| Instancia | `i-06a5651301e9b6c39`, `t3.medium`, Amazon Linux 2023, disco gp3 de 30 GB cifrado, IMDSv2 obligatorio (2 saltos para los contenedores), **sin llave SSH** |
| IP elástica | `54.80.197.58` (`eipalloc-011c7d71d4e101f41`) |
| Grupo de seguridad | `sg-0515e8eed7bc45e78` (`p4-portal-sg`): solo 80 y 443 |
| Rol / perfil de instancia | `p4-portal-ec2`: política [`deploy/politica-ec2.json`](../deploy/politica-ec2.json) + `AmazonSSMManagedInstanceCore` |
| Bucket | `p4-capturas-474665692638`: privado, cifrado, con versionado; capturas en `edge-capturas/` |
| Alerta de gasto | `p4-edge-mensual`, 20 USD al mes |

## Permisos del rol (mínimos)

- **Capturas:** leer y escribir en `edge-capturas/*` del bucket. **Sin `DeleteObject`**: el receptor nunca borra.
- **Modelos:** solo lectura de `modelos/*` y `models/*`. Única escritura: `models/clasificador/registry.json`, para que el botón "Usar para inferencia" de la página Models pueda activar una versión.
- **Listado:** `ListBucket` limitado a esos prefijos.
- **Secretos:** `ssm:PutParameter` y `ssm:GetParameter` en `/p4/*`.
- **Administración:** Session Manager, sin SSH.

La política pasa la validación de IAM Access Analyzer sin hallazgos.

## Acceso de evaluación

- **Portal y MLflow:** usuario `evaluador` con `basic_auth` de Caddy. Solo `POST /api/p4/capturas` queda fuera, y lo protege el token del dispositivo.
- **Secretos:** la contraseña y el token se generan **dentro de la instancia** al instalar y se guardan cifrados en Parameter Store. Nunca pasan por el repositorio ni por el chat. Para leerlos, desde una terminal con acceso a la cuenta:

  ```bash
  aws ssm get-parameter --name /p4/portal-evaluador --with-decryption --query Parameter.Value --output text --profile p4-equipo --region us-east-1
  ```

  ```bash
  aws ssm get-parameter --name /p4/token-dispositivo --with-decryption --query Parameter.Value --output text --profile p4-equipo --region us-east-1
  ```

  La contraseña se entrega al evaluador por un canal privado; el token, al dispositivo (variable `P4_TOKEN_DISPOSITIVO`).

## Cómo se instaló

[`deploy/instalar_ec2.sh`](../deploy/instalar_ec2.sh) se pasó como user-data al lanzar la instancia, con las variables `P4_DOMINIO`, `P4_BUCKET`, `P4_RAMA` y `P4_MODELOS_ACEPTADOS` al inicio. El script:

1. **Docker:** instala Docker, Compose v5.5.1 y Buildx v0.37.1 (solo si su SHA-256 coincide con el publicado en cada release) y agrega 2 GiB de swap.
2. **Código:** clona el repositorio en `/opt/p4/repo`.
3. **Secretos:** genera `Proyecto2/.env` (contraseñas aleatorias) y `/opt/p4/secretos/caddy.env` (hash bcrypt), ambos con permisos `600`.
4. **Arranque:** levanta `docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build` y espera a que la app quede sana.

En [`Proyecto2/docker-compose.aws.yml`](../../Proyecto2/docker-compose.aws.yml), solo Caddy publica puertos; la base de datos, MinIO, MLflow y la app quedan en la red interna de Docker. El registro de la instalación queda en `/var/log/p4-instalacion.log` de la instancia.

Los secretos nunca aparecen como argumentos de un comando (visibles en la lista de procesos): el `.env` se escribe con `printf` (interno de bash), Parameter Store se llena con un JSON temporal de root y el hash de Caddy se calcula leyendo la contraseña por stdin.

## Modelo del P3 en el portal desplegado

Las páginas Models e Inference leen el paquete del modelo del P3 en el bucket del P4 (`P3_MODELS_BUCKET`). Se publicó el 15 de octubre con el script del propio P3:

```bash
cd Proyecto3
.venv/Scripts/python scripts/publish_model.py --version 1.0.0 --selected --activate --bucket p4-capturas-474665692638 --profile p4-equipo
```

Quedó en `s3://p4-capturas-474665692638/models/clasificador/`: `registry.json` con la versión `1.0.0` activa (run `9f9b62c202f0446a8a4b411a10321eff`) y `1.0.0/` con `model.pt` (SHA-256 `e4acca429ebf73d0e5a60fb0dda383a6a5322dccb1decf04b4e40ab9db989172`, VersionId `9ZtxYbQ54OLBbZgcbI3fYKuZjBEatWPc`), `MODEL_CARD.md`, `class_map.json`, `preprocessing.json`, `config.json`, `model_version.json` y el lockfile. En el portal desplegado, `GET /api/p3/models` responde con `1.0.0` activa y el objeto existente, y `POST /api/p3/models/1.0.0/activate` responde 200.

Con un perfil de `aws login`, boto3 necesita `awscrt` en el entorno del P3 (`pip install "botocore[crt]==<version de botocore>"`).

## Operación (Session Manager, sin SSH)

Ver el estado de los contenedores:

```bash
aws ssm send-command --instance-ids i-06a5651301e9b6c39 --document-name AWS-RunShellScript --parameters 'commands=["cd /opt/p4/repo/Proyecto2 && docker compose -f docker-compose.yml -f docker-compose.aws.yml ps"]' --profile p4-equipo --region us-east-1
```

Actualizar el código desplegado:

```bash
aws ssm send-command --instance-ids i-06a5651301e9b6c39 --document-name AWS-RunShellScript --parameters 'commands=["cd /opt/p4/repo && sudo -u ec2-user git pull && cd Proyecto2 && docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build"]' --profile p4-equipo --region us-east-1
```

**Después de fusionar este despliegue,** cambiar el clon de la instancia de la rama de trabajo a `main`, para que `git pull` siga funcionando cuando la rama se borre:

```bash
aws ssm send-command --instance-ids i-06a5651301e9b6c39 --document-name AWS-RunShellScript --parameters 'commands=["cd /opt/p4/repo && sudo -u ec2-user git fetch origin && sudo -u ec2-user git switch main && sudo -u ec2-user git pull"]' --profile p4-equipo --region us-east-1
```

Cambiar los modelos aceptados por el receptor: editar `P4_MODELOS_ACEPTADOS` en `/opt/p4/repo/Proyecto2/.env` y volver a correr el `up -d` de arriba.

## Costo y apagado

Alrededor de 1.2 USD al día (EC2 `t3.medium`, IP pública y disco). Después de la evaluación, apagar o terminar la instancia y liberar la IP elástica: una IP elástica sin instancia también cobra.
