#!/bin/bash
# Instala y arranca el portal (P1-P3 + Capturas Edge) en una EC2 Amazon Linux 2023.
# Se pasa como user-data al lanzar la instancia (Proyecto4/docs/despliegue.md); corre
# una vez como root. Registro completo en /var/log/p4-instalacion.log.
#
# Antes de este script, el user-data define:
#   P4_DOMINIO   <ip-con-guiones>.sslip.io de la IP elastica
#   P4_BUCKET    bucket del P4 (capturas)
#   P4_RAMA      rama del repositorio a desplegar (main una vez fusionado el despliegue)
#   P4_MODELOS_ACEPTADOS  version=sha256 del modelo optimizado (puede ir vacio)
#
# Secretos: se generan AQUI, en la instancia. Los que necesita una persona (token del
# dispositivo y contrasena del evaluador) van a Parameter Store como SecureString
# (/p4/...); nada se imprime en el registro ni va a Git. AWS: rol de la instancia.
set -euo pipefail
exec > >(tee -a /var/log/p4-instalacion.log) 2>&1
echo "== inicio $(date -u +%FT%TZ)"

: "${P4_DOMINIO:?}" "${P4_BUCKET:?}" "${P4_RAMA:?}"
P4_MODELOS_ACEPTADOS="${P4_MODELOS_ACEPTADOS:-}"
REPO_URL=https://github.com/White-eclipse1/MP4_Equipo05.git
REPO=/opt/p4/repo
SECRETOS=/opt/p4/secretos
COMPOSE_VERSION=v5.5.1
BUILDX_VERSION=v0.37.1
# SHA-256 publicados en cada release (docker-compose-linux-x86_64.sha256 y checksums.txt).
COMPOSE_SHA256=db1889184726840f75c4f9c001048430d4f25b3be3cb084d3ddd762bc0aed576
BUILDX_SHA256=9447199cdb435f25880548343c128a4b6650e8891ee598905d8d29d39a8e359b
CADDY_IMAGEN=caddy:2.11.4-alpine
REGION=us-east-1

echo "== paquetes y Docker"
dnf install -y docker git
systemctl enable --now docker
usermod -aG docker ec2-user
PLUGINS=/usr/local/lib/docker/cli-plugins
mkdir -p "$PLUGINS"
curl -fsSL -o "$PLUGINS/docker-compose" \
  "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64"
curl -fsSL -o "$PLUGINS/docker-buildx" \
  "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-amd64"
# Binarios que corren como root: se instalan solo si su SHA-256 es el publicado.
echo "$COMPOSE_SHA256  $PLUGINS/docker-compose" | sha256sum -c -
echo "$BUILDX_SHA256  $PLUGINS/docker-buildx" | sha256sum -c -
chmod +x "$PLUGINS/docker-compose" "$PLUGINS/docker-buildx"
docker compose version
docker buildx version

echo "== swap de 2 GiB (la imagen de P3 trae PyTorch)"
if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "== repositorio (${P4_RAMA})"
if [ ! -d "$REPO/.git" ]; then
  git clone --branch "$P4_RAMA" "$REPO_URL" "$REPO"
fi
chown -R ec2-user:ec2-user "$REPO"
# El clon es de ec2-user y los comandos de este script corren como root: sin esto git
# se niega a leerlo ("dubious ownership").
git config --system --add safe.directory "$REPO"
git -C "$REPO" log -1 --format="commit %H %s"

echo "== secretos (generados aqui; no se imprimen)"
install -d -m 700 "$SECRETOS"
ENV="$REPO/Proyecto2/.env"
if [ ! -f "$ENV" ]; then
  cp "$REPO/Proyecto2/.env.example" "$ENV"
  # poner VARIABLE valor: reemplaza la linea. `printf` es interno de bash, asi que el
  # valor (a veces un secreto) nunca aparece como argumento en la lista de procesos.
  poner() {
    grep -v "^$1=" "$ENV" > "$ENV.tmp" || true
    printf '%s=%s\n' "$1" "$2" >> "$ENV.tmp"
    mv "$ENV.tmp" "$ENV"
  }
  poner DB_PASSWORD "$(openssl rand -hex 24)"
  poner DB_ROOT_PASSWORD "$(openssl rand -hex 24)"
  poner MINIO_ROOT_PASSWORD "$(openssl rand -hex 24)"
  poner DQ_UID "$(id -u ec2-user)"
  poner DQ_GID "$(id -g ec2-user)"
  poner P4_DOMINIO "$P4_DOMINIO"
  poner P4_BUCKET "$P4_BUCKET"
  poner P4_TOKEN_DISPOSITIVO "$(openssl rand -hex 32)"
  poner P4_MODELOS_ACEPTADOS "$P4_MODELOS_ACEPTADOS"
  chown ec2-user:ec2-user "$ENV"
  chmod 600 "$ENV"
fi
# Guarda un secreto en Parameter Store sin pasarlo como argumento: va en un JSON
# temporal legible solo por root, que se borra enseguida.
guardar_secreto() {
  local archivo
  archivo=$(mktemp)
  printf '{"Name": "%s", "Value": "%s", "Type": "SecureString", "Overwrite": true}' "$1" "$2" > "$archivo"
  aws ssm put-parameter --region "$REGION" --cli-input-json "file://$archivo" > /dev/null
  rm -f "$archivo"
}
TOKEN=$(grep '^P4_TOKEN_DISPOSITIVO=' "$ENV" | cut -d= -f2-)
guardar_secreto /p4/token-dispositivo "$TOKEN"

if [ ! -f "$SECRETOS/caddy.env" ]; then
  CLAVE=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)
  # Por stdin y no con --plaintext: asi la contrasena no aparece en la lista de procesos.
  HASH=$(printf '%s\n' "$CLAVE" | docker run -i --rm "$CADDY_IMAGEN" caddy hash-password)
  {
    echo "P4_DOMINIO=$P4_DOMINIO"
    echo "P4_PORTAL_USUARIO=evaluador"
    # Comillas simples: el hash bcrypt lleva '$' y compose no debe interpolarlo.
    echo "P4_PORTAL_HASH='$HASH'"
  } > "$SECRETOS/caddy.env"
  chmod 600 "$SECRETOS/caddy.env"
  guardar_secreto /p4/portal-evaluador "$CLAVE"
  unset CLAVE HASH
fi
unset TOKEN

echo "== arranque del portal"
cd "$REPO/Proyecto2"
docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build
# La primera vez construye las imagenes (PyTorch incluido): hasta 30 min para la app.
for _ in $(seq 1 180); do
  estado=$(docker inspect --format '{{.State.Health.Status}}' dq_app 2>/dev/null || echo ausente)
  [ "$estado" = healthy ] && break
  sleep 10
done
echo "app: $estado"
docker compose -f docker-compose.yml -f docker-compose.aws.yml ps
[ "$estado" = healthy ] || { echo "== la app no quedo sana"; exit 1; }
echo "== fin $(date -u +%FT%TZ): https://${P4_DOMINIO}"
