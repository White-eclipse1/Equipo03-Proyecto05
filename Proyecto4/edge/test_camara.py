"""Pruebas de EDGE-02 sin cámara real; ejecutar con unittest discover."""

from contextlib import redirect_stdout
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import camara


class CamaraTests(unittest.TestCase):
    def test_capturas_unicas_jpeg_fecha_y_log(self):
        foto = io.BytesIO()
        Image.new("RGB", (32, 24), "blue").save(foto, "JPEG")
        datos = foto.getvalue()
        with tempfile.TemporaryDirectory() as temporal, redirect_stdout(io.StringIO()):
            carpeta = Path(temporal)
            registros = []
            for _ in range(2):
                with patch.object(camara, "urlopen", return_value=io.BytesIO(datos)):
                    registros.append(camara.capturar("http://camara/shot.jpg", carpeta, "edge01"))
            self.assertNotEqual(registros[0]["capture_id"], registros[1]["capture_id"])
            for registro in registros:
                self.assertIsNotNone(datetime.fromisoformat(registro["captured_at"]).utcoffset())
                ruta = Path(registro["image_ref"])
                self.assertEqual(ruta.read_bytes(), datos)
                self.assertEqual(json.loads(ruta.with_suffix(".json").read_text()), registro)
            self.assertEqual(len((carpeta / "capturas.jsonl").read_text().splitlines()), 2)

    def test_respuesta_invalida_no_genera_captura(self):
        with tempfile.TemporaryDirectory() as temporal:
            carpeta = Path(temporal)
            with patch.object(camara, "urlopen", return_value=io.BytesIO(b"no es JPEG")):
                with self.assertRaises(OSError):
                    camara.capturar("http://camara/shot.jpg", carpeta, "edge01")
            self.assertEqual(list(carpeta.iterdir()), [])

    def test_error_visible_y_persistente(self):
        with tempfile.TemporaryDirectory() as temporal:
            argumentos = ["camara.py", "--url", "http://camara/shot.jpg", "--salida", temporal,
                          "--intervalo", "1"]
            with patch("sys.argv", argumentos), patch.object(camara, "urlopen", side_effect=TimeoutError()):
                with redirect_stdout(io.StringIO()) as salida:
                    self.assertEqual(camara.main(), 1)
            self.assertIn("error_camara", salida.getvalue())
            registro = json.loads((Path(temporal) / "capturas.jsonl").read_text())
            self.assertEqual(registro["estado"], "error_camara")
