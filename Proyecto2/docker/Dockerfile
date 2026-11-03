# syntax=docker/dockerfile:1

# --- Etapa 1: compilar la app web (Frente 7) --------------------------------
FROM node:22-slim AS web

WORKDIR /web
# Las dependencias cambian mucho menos que el codigo: capa propia y cacheada.
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Se compila a /web/dist en vez del outDir del vite.config, porque dentro de
# esta etapa no existe el arbol `src/` del repositorio.
RUN npx vite build --outDir /web/dist --emptyOutDir


# --- Etapa 2: la aplicacion --------------------------------------------------
# `app` es la imagen de desarrollo y de CI: compose la pide con `target: app` y
# monta encima el codigo de P2 y P3 para recargar en caliente.
FROM python:3.12-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # El paquete se instala editable para recarga en desarrollo; conservar la
    # ruta explicita hace que uvicorn encuentre tanto la app como el sidecar.
    PYTHONPATH=/app/src

WORKDIR /app

# Las dependencias cambian mucho menos que el codigo: capa propia y cacheada.
#
# El lockfile va PRIMERO y en su propia capa: fija la version exacta de las 153
# dependencias transitivas, y como cambia mucho menos que `pyproject.toml`, la
# capa sobrevive a casi cualquier edicion del proyecto. Instalarlo antes que el
# paquete tambien es lo que hace que la imagen sea reproducible: `pip install -e
# .` a secas resolveria los rangos de `pyproject.toml` de nuevo en cada build y
# dos imagenes construidas con una semana de diferencia no tendrian el mismo
# arbol de dependencias.
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY pyproject.toml README.md quality.yaml ./
COPY src ./src
# El lockfile ya trajo todo lo que hace falta, incluido el extra `pipeline`
# (DVC): esto solo registra `dataset_quality` como paquete editable y el
# comando `dq`. `--no-deps` impide que pip vuelva a resolver los rangos de
# `pyproject.toml` y deshaga los pines de la capa anterior.
RUN pip install --no-cache-dir --no-deps -e "."

# DVC dentro de la imagen, y no solo en el host de quien desarrolla: es lo que
# permite verificar la reproducibilidad del pipeline (`dvc repro`, `dvc status
# -r dev`) en el mismo entorno que se evalua, sin depender de que el evaluador
# tenga DVC instalado. Se comprueba aqui para que un lockfile que se quede sin
# el extra `pipeline` rompa el build en vez de dejar una imagen a medias.
RUN dvc --version && dq --version

# El build de la web va FUERA de `src/`, y `DQ_STATIC_DIR` le dice a `main.py`
# donde buscarlo. Dentro de `src/` no puede vivir: compose monta ahi el codigo
# del host para recargar uvicorn en caliente, y ese montaje taparia el build
# que esta imagen acaba de compilar. Como el build esta en `.gitignore`, el
# host de quien clona el repositorio no tiene nada que poner en su lugar.
COPY --from=web /web/dist /opt/dq/static
ENV DQ_STATIC_DIR=/opt/dq/static

# Usuario sin privilegios: el contenedor nunca corre como root.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app /opt/dq
USER appuser

EXPOSE 8000

CMD ["uvicorn", "dataset_quality.main:app", "--host", "0.0.0.0", "--port", "8000"]

