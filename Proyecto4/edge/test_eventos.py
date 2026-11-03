"""EDGE-05: contrato, correspondencia, conflictos y persistencia ante error de red."""

from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import URLError

from PIL import Image

import eventos


class EventosTests(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.base = Path(self.temporal.name)
        foto = self.base / "edge01-test.jpg"
        Image.new("RGB", (32, 24), "red").save(foto, "JPEG")
        self.captura = {
            "capture_id": foto.stem, "image_ref": str(foto),
            "image_sha256": hashlib.sha256(foto.read_bytes()).hexdigest(),
            "captured_at": datetime.now().astimezone().isoformat(), "device_id": "edge01",
            "estado": "capturada", "width": 32, "height": 24, "image_bytes": foto.stat().st_size,
        }
        self.prediccion = {"predicted_class": "cat", "confidence": 0.9,
                           "logits": [3, 0, 0], "probabilities": [0.9, 0.05, 0.05]}
        self.modelo = SimpleNamespace(hash="a" * 64)

    def evento(self):
        return eventos.construir_evento(self.captura, self.prediccion, self.modelo)

    def test_solo_campos_del_contrato_y_vinculo(self):
        evento = self.evento()
        self.assertEqual(set(evento), {
            "schema_version", "capture_id", "captured_at", "predicted_class", "confidence",
            "device_id", "model_version", "model_sha256", "image_sha256", "image_ref", "region",
        })
        self.assertEqual(evento["capture_id"], self.captura["capture_id"])
        self.assertEqual(evento["confidence"], 0.9)
        self.assertEqual(evento["model_sha256"], self.modelo.hash)
        self.assertIsNone(evento["region"])

    def test_rechaza_foto_alterada(self):
        Path(self.captura["image_ref"]).write_bytes(b"cambio")
        with self.assertRaisesRegex(ValueError, "no corresponden"):
            self.evento()

    def test_rechaza_confianza_fecha_y_campos_extra(self):
        for confianza in (True, "0.9", float("nan"), -0.1, 1.1):
            evento = self.evento()
            evento["confidence"] = confianza
            with self.subTest(confianza=confianza), self.assertRaises(ValueError):
                eventos.validar_evento(evento)
        for cambios in ({"captured_at": "2026-10-16T10:00:00"}, {"width": 1920}):
            evento = self.evento() | cambios
            with self.assertRaises(ValueError):
                eventos.validar_evento(evento)

    def test_idempotencia_local_y_conflicto_sin_sobrescribir(self):
        evento = self.evento()
        ruta = eventos.guardar_evento(self.base / "eventos", evento)
        original = ruta.read_bytes()
        self.assertEqual(eventos.guardar_evento(self.base / "eventos", evento), ruta)
        with self.assertRaisesRegex(ValueError, "Conflicto"):
            eventos.guardar_evento(self.base / "eventos", evento | {"confidence": 0.8})
        self.assertEqual(ruta.read_bytes(), original)
        self.assertEqual(json.loads(original), evento)

    def test_fallo_envio_lee_archivos_guardados_y_no_los_borra(self):
        evento = self.evento()
        ruta = eventos.guardar_evento(self.base / "eventos", evento)
        antes = ruta.read_bytes()
        foto = Path(evento["image_ref"])
        foto_antes = foto.read_bytes()

        def fallar(solicitud, **kwargs):
            self.assertEqual(ruta.read_bytes(), antes)
            self.assertIn(antes, solicitud.data)
            self.assertIn(foto_antes, solicitud.data)
            raise URLError("fallo controlado de prueba")

        with patch.object(eventos, "urlopen", side_effect=fallar), patch("sys.stdout", io.StringIO()):
            eventos.probar_fallo_envio(ruta, self.base / "log.jsonl")
        self.assertEqual(ruta.read_bytes(), antes)
        self.assertEqual(foto.read_bytes(), foto_antes)
        evidencia = json.loads((self.base / "log.jsonl").read_text())
        self.assertTrue(evidencia["bytes_intactos"])
        self.assertEqual(evidencia["estado"], "fallo_envio_controlado")
