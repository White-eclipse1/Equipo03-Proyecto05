"""Prueba de continuidad ante fallo, export y configuración estable entre procesos."""

import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import operacion


class OperacionTests(unittest.TestCase):
    def test_errores_visibles_continua_y_reinicio_misma_config(self):
        modelo = SimpleNamespace(hash="a" * 64, metadatos={"estado": "modelo_cargado"},
                                 predecir=lambda datos: {"predicted_class": "cat", "confidence": 0.9})
        with tempfile.TemporaryDirectory() as temporal:
            base = Path(temporal)
            foto = base / "foto.jpg"
            foto.write_bytes(b"foto ficticia solo para prueba")
            evento = {"capture_id": "edge01-test", "predicted_class": "cat"}
            with patch("builtins.input", return_value=""), patch("sys.stdout", io.StringIO()):
                with patch.object(operacion, "Modelo", return_value=modelo) as constructor:
                    with patch.object(operacion, "capturar", side_effect=[OSError(), {"image_ref": str(foto)}, {"image_ref": str(foto)}]):
                        with patch.object(operacion, "construir_evento", return_value=evento):
                            with patch.object(operacion, "guardar_evento", return_value=base / "evento.json"):
                                with patch.object(operacion.time, "sleep"):
                                    self.assertEqual(operacion.ejecutar(base / "modelo", "http://camara/shot.jpg", base, cantidad=2), 1)
                                    self.assertEqual(operacion.ejecutar(base / "modelo", "http://camara/shot.jpg", base, cantidad=1, fase="reinicio"), 0)
            self.assertEqual(constructor.call_count, 2)
            registros = [json.loads(x) for x in (base / "operacion.jsonl").read_text(encoding="utf-8").splitlines()]
            cargas = [r for r in registros if r["estado"] == "modelo_cargado"]
            self.assertEqual(len({r["session_id"] for r in cargas}), 2)
            self.assertEqual(len({r["config_sha256"] for r in cargas}), 1)
            self.assertEqual(sum(r["estado"] == "fallo_captura" for r in registros), 1)
            self.assertEqual(sum(r["estado"] == "captura_completa" for r in registros), 2)
            self.assertEqual(len((base / "historial.jsonl").read_text().splitlines()), 2)
