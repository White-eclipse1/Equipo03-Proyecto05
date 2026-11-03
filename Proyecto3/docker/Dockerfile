# Imagen del worker de entrenamiento de Proyecto 3.
# Se construye desde `Proyecto2/docker-compose.yml` (servicio `p3-worker`) con
# `Proyecto3/` como contexto. Python 3.12 fijado igual que en Proyecto2.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TORCH_HOME=/opt/torch \
    CUBLAS_WORKSPACE_CONFIG=:4096:8

WORKDIR /app

# Dependencias desde el lockfile, antes del codigo: cambiar un .py no reinstala.
#
# TORCH_VARIANT=cpu (por defecto): las mismas versiones de torch y torchvision
# del lockfile, en su wheel de CPU del indice de PyTorch (`+cpu`), sin los ~3 GB
# de CUDA (nvidia-*, cuda-*, triton). Asi arrancan p3-inference, la CI y una
# maquina sin GPU. TORCH_VARIANT=cuda instala el lockfile tal cual; lo pide
# `docker-compose.gpu.yml` solo para p3-worker cuando hay GPU NVIDIA.
ARG TORCH_VARIANT=cpu
COPY requirements.lock.txt ./
RUN set -eu; \
    case "$TORCH_VARIANT" in \
      cuda) pip install --no-cache-dir -r requirements.lock.txt ;; \
      cpu) sed -E \
             -e "/ ; sys_platform == 'linux'/d" \
             -e 's/^(torch|torchvision)==([^ ;+]+)$/\1==\2+cpu/' \
             requirements.lock.txt > /tmp/requirements.cpu.txt \
           && pip install --no-cache-dir \
                --extra-index-url https://download.pytorch.org/whl/cpu \
                -r /tmp/requirements.cpu.txt ;; \
      *) echo "TORCH_VARIANT debe ser cpu o cuda, no '$TORCH_VARIANT'" >&2; exit 1 ;; \
    esac

# Pesos de ImageNet de ResNet-18 dentro de la imagen: las corridas no dependen
# de la red y todas parten del mismo archivo (torchvision verifica su hash).
RUN python -c "from torchvision.models import ResNet18_Weights; ResNet18_Weights.IMAGENET1K_V1.get_state_dict(progress=False)" \
    && chmod -R a+rX /opt/torch

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps -e .

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "p3.worker.runner"]
