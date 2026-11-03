PYTHON ?= $(shell which python3 2>/dev/null || which python 2>/dev/null || echo python3)

.PHONY: up down logs test lint fmt shell check

check:       ## Validacion rapida completa en <30s (Ruff + Pytest + Terraform + Secretos)
	$(PYTHON) scripts/check.py

up:          ## Levanta todo el entorno local (app + MariaDB + MinIO)
	$(PYTHON) scripts/up.py

down:        ## Apaga los contenedores (conserva los datos)
	$(PYTHON) scripts/down.py

logs:        ## Sigue los logs de la app
	docker compose logs -f app

test:        ## Corre la suite de pytest
	pytest

lint:        ## Ruff en modo verificacion
	ruff check . && ruff format --check .

fmt:         ## Ruff en modo escritura
	ruff check --fix . && ruff format .

shell:       ## Shell dentro del contenedor de la app
	docker compose exec app bash

