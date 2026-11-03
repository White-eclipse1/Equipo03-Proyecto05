"""Exporta el dataset del Proyecto 1 y verifica el minimo del curso (M3).

    python scripts/export_from_mp1.py

Hace dos cosas:

  1. **Exporta.** Descarga el COCO y los binarios de las imagenes del portal de
     anotacion a `data/raw/`, que es donde el pipeline del Proyecto 2 los busca.
  2. **Verifica el minimo.** Cuenta imagenes DISTINTAS por clase y dice cuantas
     faltan para cumplir la compuerta M3: al menos 300 imagenes en al menos 2
     clases. Correrlo a diario es la forma barata de no descubrir el dia de la
     entrega que la anotacion no alcanzo.

Por que por HTTP y no leyendo su base de datos: `/api/coco/export` es el
contrato publico que el propio README del Proyecto 1 declara como entregable.
Asi el Proyecto 2 no se acopla a su esquema de Drizzle ni necesita sus
credenciales de MariaDB o MinIO.

Por que fuera del pipeline: esta descarga ocurre UNA VEZ. El pipeline (`dvc
repro`) solo lee `data/raw/`, de modo que sigue siendo reproducible aunque el
Proyecto 1 no este corriendo — que es exactamente la situacion del evaluador.

Solo usa la libreria estandar: no hace falta instalar nada para correrlo.
"""

from __future__ import annotations

import argparse
import http.client
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
IMAGES_DIR = RAW_DIR / "images"
ANNOTATIONS_PATH = RAW_DIR / "annotations.coco.json"

DEFAULT_BASE_URL = "http://localhost:3000"
MIN_IMAGES = 300
MIN_CLASSES = 2

GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[90m", "\033[0m"


def log(message: str) -> None:
    print(f"\n\033[35m==>\033[0m {message}", flush=True)


def fail(message: str) -> None:
    print(f"\n{RED}Error:{RESET} {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def base_url_from_env() -> str:
    """Lee `MP1_BASE_URL` de `.env` si esta definido."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return DEFAULT_BASE_URL
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("MP1_BASE_URL=") and "=" in line:
            value = line.partition("=")[2].strip().strip('"').strip("'")
            if value:
                return value
    return DEFAULT_BASE_URL


class Client:
    """Cliente HTTP con conexion reutilizada y reintentos.

    Descargar ~900 imagenes abriendo una conexion nueva cada vez agota los
    puertos efimeros de Windows y el servidor acaba cortando (`WinError 10054`).
    Con keep-alive es una sola conexion, y si aun asi se cae se reconecta y
    reintenta en vez de abortar la descarga entera.
    """

    def __init__(self, base_url: str, timeout: int = 60, retries: int = 4) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"}:
            fail(f"URL no valida: {base_url!r}. Debe empezar por http:// o https://")
        self._secure = parsed.scheme == "https"
        self._host = parsed.hostname or "localhost"
        self._port = parsed.port or (443 if self._secure else 80)
        self._timeout = timeout
        self._retries = retries
        self._connection: http.client.HTTPConnection | None = None

    def _connect(self) -> http.client.HTTPConnection:
        if self._connection is None:
            factory = http.client.HTTPSConnection if self._secure else http.client.HTTPConnection
            self._connection = factory(self._host, self._port, timeout=self._timeout)
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def get(self, path: str) -> bytes:
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                connection = self._connect()
                connection.request("GET", path, headers={"Connection": "keep-alive"})
                response = connection.getresponse()
                body = response.read()  # siempre, para dejar la conexion reutilizable
                if response.status >= 400:
                    raise urllib.error.HTTPError(path, response.status, response.reason, {}, None)
                return body
            except urllib.error.HTTPError:
                raise
            except (OSError, http.client.HTTPException) as error:
                # Conexion caida: se descarta y se reintenta con una nueva.
                last = error
                self.close()
                if attempt < self._retries - 1:
                    time.sleep(0.4 * (attempt + 1))
        raise ConnectionError(f"GET {path} fallo tras {self._retries} intentos: {last}")


def validate_coco(dataset: dict) -> None:
    """Comprobaciones de integridad antes de escribir nada en disco.

    No sustituye a los modelos Pydantic del Frente 2: es el minimo para no
    descargar 900 imagenes de un archivo que luego se va a rechazar.
    """
    problems: list[str] = []

    for key in ("images", "annotations", "categories"):
        if not isinstance(dataset.get(key), list):
            problems.append(f"falta la lista `{key}`")
    if problems:
        fail("El COCO no tiene la forma esperada -> " + "; ".join(problems))

    image_ids = {item["id"] for item in dataset["images"]}
    category_ids = {item["id"] for item in dataset["categories"]}

    if len(image_ids) != len(dataset["images"]):
        problems.append("hay ids de imagen duplicados")
    if len(category_ids) != len(dataset["categories"]):
        problems.append("hay ids de categoria duplicados")

    orphans = [a["id"] for a in dataset["annotations"] if a["image_id"] not in image_ids]
    if orphans:
        problems.append(f"{len(orphans)} anotaciones apuntan a una imagen inexistente")

    classless = [a["id"] for a in dataset["annotations"] if a["category_id"] not in category_ids]
    if classless:
        problems.append(f"{len(classless)} anotaciones apuntan a una clase inexistente")

    for image in dataset["images"]:
        name = image["file_name"]
        if "/" in name or "\\" in name or name in {".", ".."}:
            problems.append(f"`file_name` con separadores de ruta: {name!r}")
            break

    if problems:
        fail("COCO invalido -> " + "; ".join(problems))


def images_per_class(dataset: dict) -> dict[str, int]:
    """Imagenes DISTINTAS que contienen al menos una caja de cada clase.

    Esta es la metrica que exige el curso, y no es lo mismo que contar cajas:
    una foto con siete coches aporta UNA imagen a `car`, no siete.
    """
    names = {item["id"]: item["name"] for item in dataset["categories"]}
    buckets: dict[str, set[int]] = defaultdict(set)
    for annotation in dataset["annotations"]:
        buckets[names[annotation["category_id"]]].add(annotation["image_id"])
    return {name: len(buckets.get(name, set())) for name in sorted(names.values())}


def download_images(client: Client, dataset: dict, fresh: bool) -> tuple[int, int]:
    """Descarga el binario de cada imagen.

    El `id` de `coco.images[]` es el mismo que el de `/api/images/{id}/file`:
    esa es la llave que une las dos mitades del export.
    """
    if fresh and IMAGES_DIR.exists():
        shutil.rmtree(IMAGES_DIR)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    downloaded = skipped = 0
    total = len(dataset["images"])
    for index, image in enumerate(dataset["images"], start=1):
        target = IMAGES_DIR / image["file_name"]
        if target.exists() and target.stat().st_size > 0:
            skipped += 1
            continue
        try:
            target.write_bytes(client.get(f"/api/images/{image['id']}/file"))
        except urllib.error.HTTPError as error:
            fail(
                f"El Proyecto 1 devolvio {error.code} para la imagen "
                f"{image['id']} ({image['file_name']})."
            )
        except ConnectionError as error:
            # Lo ya descargado se conserva: volver a correr el script retoma
            # donde se quedo en vez de empezar de cero.
            fail(f"{error}\nVuelve a correr el script para retomar la descarga.")
        downloaded += 1
        if index % 50 == 0 or index == total:
            print(f"  {index}/{total}", flush=True)
    return downloaded, skipped


def report_minimum(counts: dict[str, int], min_images: int, min_classes: int) -> bool:
    """Imprime el estado de la compuerta M3 y devuelve si se cumple."""
    ranked = sorted(counts.items(), key=lambda item: -item[1])
    qualifying = [name for name, count in ranked if count >= min_images]

    print(f"\n{'clase':<16}{'imagenes':>10}   estado")
    print("-" * 46)
    for name, count in ranked:
        if count >= min_images:
            estado = f"{GREEN}OK{RESET}"
        else:
            estado = f"{YELLOW}faltan {min_images - count}{RESET}"
        print(f"{name:<16}{count:>10}   {estado}")

    ok = len(qualifying) >= min_classes
    print()
    if ok:
        print(
            f"{GREEN}Minimo cumplido.{RESET} {len(qualifying)} clases con >= {min_images}: "
            f"{', '.join(qualifying)}"
        )
    else:
        faltan = min_classes - len(qualifying)
        # Las mas cercanas son las candidatas naturales a terminar primero.
        objetivo = [f"{name} (+{min_images - count})" for name, count in ranked[:min_classes]]
        print(
            f"{RED}Minimo NO cumplido.{RESET} Hacen falta {faltan} clase(s) mas "
            f"con >= {min_images} imagenes."
        )
        print(f"Las mas cercanas: {', '.join(objetivo)}")

    print(
        f"\n{DIM}Nota: este conteo es ANTES de colapsar casi-duplicados. El evaluador\n"
        f"cuenta despues, asi que el numero real puede ser menor. El analizador de\n"
        f"duplicados (Frente 3) dara la cifra definitiva.{RESET}"
    )
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exporta el dataset del Proyecto 1 y verifica el minimo M3."
    )
    parser.add_argument("--base-url", default=None, help="URL del portal de anotacion")
    parser.add_argument(
        "--fresh", action="store_true", help="Borra las imagenes locales antes de descargar"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Solo consulta el conteo por clase; no descarga imagenes",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Sale con codigo 1 si no se cumple el minimo (util en CI)",
    )
    parser.add_argument("--min-images", type=int, default=MIN_IMAGES)
    parser.add_argument("--min-classes", type=int, default=MIN_CLASSES)
    args = parser.parse_args()

    base_url = (args.base_url or base_url_from_env()).rstrip("/")

    client = Client(base_url, timeout=120)

    log(f"Consultando {base_url}/api/coco/export")
    try:
        payload = client.get("/api/coco/export")
    except (urllib.error.URLError, ConnectionError, OSError) as error:
        fail(
            f"No se pudo hablar con el Proyecto 1 en {base_url}: {error}\n"
            f"Levantalo con `npm run up` en su repositorio y vuelve a intentar."
        )

    dataset = json.loads(payload)
    validate_coco(dataset)
    print(
        f"COCO valido: {len(dataset['images'])} imagenes, "
        f"{len(dataset['annotations'])} cajas, {len(dataset['categories'])} clases"
    )

    counts = images_per_class(dataset)

    if not args.check_only:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        ANNOTATIONS_PATH.write_text(json.dumps(dataset, indent=1), encoding="utf-8", newline="\n")
        print(f"COCO guardado en {ANNOTATIONS_PATH.relative_to(REPO_ROOT)}")

        log("Descargando imagenes...")
        downloaded, skipped = download_images(client, dataset, args.fresh)
        print(f"\n{downloaded} descargadas, {skipped} ya estaban en disco.")

    client.close()

    log("Estado de la compuerta M3")
    ok = report_minimum(counts, args.min_images, args.min_classes)

    if not args.check_only and ok:
        print("\nSiguiente paso: dq ingest")

    if args.strict and not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrumpido.")
        raise SystemExit(130) from None
