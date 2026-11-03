"""Pruebas sin binario ONNX; no sustituyen validación física."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

import inferencia as edge


class InferenciaTests(unittest.TestCase):
    def test_preprocesamiento_rgb_nchw_y_normalizacion(self):
        tensor = edge.preprocesar(Image.new("RGB", (40, 20), "red"))
        self.assertEqual(tensor.shape, (1, 3, 224, 224))
        self.assertEqual(tensor.dtype, np.float32)
        np.testing.assert_allclose(tensor[0, :, 0, 0],
                                   (np.array([1, 0, 0]) - [0.485, 0.456, 0.406]) /
                                   [0.229, 0.224, 0.225], rtol=1e-6)
        probs = edge.softmax(np.array([[1000., 1001., 1002.]]))
        self.assertTrue(np.isfinite(probs).all())
        self.assertAlmostEqual(float(probs.sum()), 1.)

    def test_hash_incorrecto_no_invoca_runtime(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "modelo.onnx"
            ruta.write_bytes(b"incorrecto")
            runtime = Mock()
            with patch.dict("sys.modules", {"onnxruntime": runtime}):
                with self.assertRaisesRegex(ValueError, "Hash incorrecto"):
                    edge.Modelo(ruta)
            runtime.InferenceSession.assert_not_called()

    def test_carga_bytes_verificados_cpu_y_prediccion(self):
        datos = b"modelo simulado solo para test"
        sesion = Mock()
        sesion.get_inputs.return_value = [SimpleNamespace(name="entrada", type="tensor(float)",
                                                         shape=[1, 3, 224, 224])]
        sesion.get_outputs.return_value = [SimpleNamespace(name="logits", shape=[1, 3])]
        sesion.get_providers.return_value = ["CPUExecutionProvider"]
        sesion.run.return_value = [np.array([[0., 3., 1.]], dtype=np.float32)]
        runtime = SimpleNamespace(__version__="test", InferenceSession=Mock(return_value=sesion))
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "modelo.onnx"
            ruta.write_bytes(datos)
            with patch.object(edge, "SHA256", hashlib.sha256(datos).hexdigest()):
                with patch.dict("sys.modules", {"onnxruntime": runtime}):
                    modelo = edge.Modelo(ruta)
            runtime.InferenceSession.assert_called_once_with(datos, providers=["CPUExecutionProvider"])
            foto = io.BytesIO()
            Image.new("RGB", (30, 30), "blue").save(foto, "JPEG")
            resultado = modelo.predecir(foto.getvalue())
            self.assertEqual(resultado["predicted_class"], "dog")
            self.assertAlmostEqual(sum(resultado["probabilities"]), 1., places=6)
            self.assertEqual(sesion.run.call_args.args[1]["entrada"].shape, (1, 3, 224, 224))

    def test_jpeg_modificado_no_se_infiere(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "edge01-test.jpg"
            ruta.write_bytes(b"cambiado")
            ruta.with_suffix(".json").write_text(json.dumps({
                "capture_id": ruta.stem, "image_sha256": "0" * 64,
            }))
            modelo = Mock()
            with self.assertRaisesRegex(ValueError, "no corresponde"):
                edge.procesar(modelo, ruta, "cat")
            modelo.predecir.assert_not_called()
