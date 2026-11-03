"""Transporte EDGE-06: multipart real, idempotencia, reintentos y protección de logs."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from PIL import Image

import enviar


class Respuesta(io.BytesIO):
    def __init__(self, estado):
        super().__init__(json.dumps({"capture_id": "edge01-test",
                                    "estado": "creado" if estado == 201 else "duplicado"}).encode())
        self.status = estado


class EnviarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        foto = self.base / "edge01-test.jpg"
        Image.new("RGB", (32, 24), "red").save(foto, "JPEG")
        self.evento = {
            "schema_version": 1, "capture_id": "edge01-test", "captured_at": "2026-10-16T16:00:00-06:00",
            "predicted_class": "cat", "confidence": 0.9, "device_id": "edge01",
            "model_version": "1.0.0-int8-e05.1", "model_sha256": "a" * 64,
            "image_sha256": hashlib.sha256(foto.read_bytes()).hexdigest(), "image_ref": str(foto),
            "region": None,
        }
        self.ruta = self.base / "evento.json"
        self.ruta.write_text(json.dumps(self.evento))
        self.log = self.base / "envios.jsonl"
        salida = patch("sys.stdout", new_callable=io.StringIO)
        salida.start()
        self.addCleanup(salida.stop)

    def enviar(self):
        return enviar.enviar(self.ruta, enviar.RECEPTOR, "token-prueba", self.log)

    def test_creado_duplicado_y_multipart_sin_cambiar_original(self):
        original = self.ruta.read_bytes()
        abrir = Mock(side_effect=[Respuesta(201), Respuesta(200)])
        with patch.object(enviar, "build_opener", return_value=Mock(open=abrir)):
            self.assertTrue(self.enviar())
            self.assertTrue(self.enviar())
        self.assertEqual(self.ruta.read_bytes(), original)
        for llamada in abrir.call_args_list:
            solicitud = llamada.args[0]
            self.assertIn(b'name="evento"', solicitud.data)
            self.assertIn(b'name="foto"', solicitud.data)
            self.assertIn(original, solicitud.data)
            self.assertIn(Path(self.evento["image_ref"]).read_bytes(), solicitud.data)
            self.assertEqual(solicitud.get_header("Authorization"), "Bearer token-prueba")
        self.assertNotIn("token-prueba", self.log.read_text())

    def test_red_503_reintenta_mismo_cuerpo_y_no_borra(self):
        original = self.ruta.read_bytes()
        error503 = HTTPError(enviar.RECEPTOR, 503, "no disponible", {}, io.BytesIO(b'{}'))
        abrir = Mock(side_effect=[URLError("timeout"), error503, Respuesta(200)])
        with patch.object(enviar, "build_opener", return_value=Mock(open=abrir)), patch.object(enviar.time, "sleep"):
            self.assertTrue(self.enviar())
        self.assertEqual(abrir.call_count, 3)
        self.assertEqual(abrir.call_args_list[0].args[0].data, abrir.call_args_list[2].args[0].data)
        self.assertEqual(self.ruta.read_bytes(), original)

    def test_4xx_y_500_no_se_reintentan_y_token_reflejado_se_oculta(self):
        for estado in (400, 401, 409, 413, 415, 422, 429, 500):
            error = HTTPError(enviar.RECEPTOR, estado, "fallo", {}, io.BytesIO(b'token-prueba'))
            abrir = Mock(side_effect=error)
            with self.subTest(estado=estado):
                with patch.object(enviar, "build_opener", return_value=Mock(open=abrir)):
                    self.assertFalse(self.enviar())
                self.assertEqual(abrir.call_count, 1)
        self.assertNotIn("token-prueba", self.log.read_text())

    def test_metadatos_locales_o_jpeg_modificado_impiden_post(self):
        for alterar in ("extras", "foto"):
            with self.subTest(alterar=alterar):
                self.ruta.write_text(json.dumps(self.evento | ({"width": 1920} if alterar == "extras" else {})))
                if alterar == "foto":
                    Path(self.evento["image_ref"]).write_bytes(b"cambio")
                with patch.object(enviar, "build_opener") as abrir:
                    with self.assertRaises(ValueError):
                        self.enviar()
                abrir.assert_not_called()
