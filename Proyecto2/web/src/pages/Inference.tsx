/**
 * Inference (P3): subir una imagen, recortar (opcional), predecir con la versión
 * activa y enviar a la cola de anotación de P1 (F9 T23).
 *
 * Valida tipo y tamaño en cliente antes de enviar (el servidor valida también:
 * 415/413/409/422). Muestra la clase predicha, la barra de probabilidades por
 * clase y la versión de modelo usada. "Enviar a anotación" sube la misma imagen
 * al flujo de P1 y muestra el elemento creado.
 */

import { useState } from 'react';
import { Card, Pill } from '../components/ui';
import { type AnnotationQueueItem, type InferenceResult, api } from '../lib/api';

const MAX_MB = 10;
const OK_TYPES = ['image/png', 'image/jpeg'];
const pct = (n: number): string => `${(n * 100).toFixed(1)}%`;

/** Los 4 campos del recorte opcional; se envían solo si los cuatro son números. */
type Box = { x: string; y: string; w: string; h: string };

function parseBox(box: Box): [number, number, number, number] | undefined {
  const nums = [box.x, box.y, box.w, box.h].map(Number);
  return nums.every((n) => Number.isFinite(n)) && [box.x, box.y, box.w, box.h].every(Boolean)
    ? (nums as [number, number, number, number])
    : undefined;
}

export default function Inference() {
  const [file, setFile] = useState<File | null>(null);
  const [box, setBox] = useState<Box>({ x: '', y: '', w: '', h: '' });
  const [fileError, setFileError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [result, setResult] = useState<InferenceResult | null>(null);
  const [predicting, setPredicting] = useState(false);
  const [sent, setSent] = useState<AnnotationQueueItem | null>(null);
  const [sending, setSending] = useState(false);

  function onPick(picked: File | null) {
    setResult(null);
    setSent(null);
    setServerError(null);
    if (!picked) {
      setFile(null);
      setFileError(null);
      return;
    }
    if (!OK_TYPES.includes(picked.type)) {
      setFile(null);
      setFileError('El archivo debe ser una imagen JPEG o PNG.');
      return;
    }
    if (picked.size > MAX_MB * 1024 * 1024) {
      setFile(null);
      setFileError(`La imagen pasa de ${MAX_MB} MB.`);
      return;
    }
    setFile(picked);
    setFileError(null);
  }

  async function predecir() {
    if (!file) return;
    setPredicting(true);
    setServerError(null);
    setResult(null);
    setSent(null);
    try {
      setResult(await api.p3.inference(file, parseBox(box)));
    } catch (e: unknown) {
      setServerError(e instanceof Error ? e.message : 'Error desconocido');
    } finally {
      setPredicting(false);
    }
  }

  async function enviarAnotacion() {
    if (!result) return;
    setSending(true);
    try {
      const { annotation_queue_item } = await api.p3.sendToAnnotation(result.inference_id);
      setSent(annotation_queue_item);
    } catch (e: unknown) {
      setServerError(e instanceof Error ? e.message : 'Error desconocido');
    } finally {
      setSending(false);
    }
  }

  const ordered = result
    ? Object.entries(result.probabilities).sort((a, b) => b[1] - a[1])
    : [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Inference</h1>
          <p className="page-sub">
            Sube una imagen, recórtala si quieres, y predice su clase con la versión de modelo
            activa. Luego puedes enviarla a la cola de anotación.
          </p>
        </div>
      </div>

      <div className="cols-2">
        <Card title="Imagen">
          <label className="field">
            <span>Imagen (JPEG o PNG, máx {MAX_MB} MB)</span>
            <input
              className="campo"
              type="file"
              accept="image/png,image/jpeg"
              onChange={(e) => onPick(e.target.files?.[0] ?? null)}
            />
          </label>
          {fileError && <div className="banner warn">{fileError}</div>}

          <p className="hint" style={{ marginTop: 14 }}>
            Recorte opcional (x, y, ancho, alto en píxeles):
          </p>
          <div className="form-grid">
            {(['x', 'y', 'w', 'h'] as const).map((k) => (
              <label className="field" key={k}>
                <span>{k}</span>
                <input
                  className="campo"
                  type="number"
                  value={box[k]}
                  onChange={(e) => setBox((b) => ({ ...b, [k]: e.target.value }))}
                />
              </label>
            ))}
          </div>

          <div className="form-actions">
            <button type="button" className="ghost" onClick={predecir} disabled={!file || predicting}>
              {predicting ? 'Prediciendo…' : 'Predecir'}
            </button>
          </div>
          {serverError && <div className="banner warn">{serverError}</div>}
        </Card>

        <Card title="Resultado">
          {result === null ? (
            <p className="state">Sube una imagen y pulsa Predecir.</p>
          ) : (
            <>
              <div className="row">
                <span>Clase predicha</span>
                <Pill kind="accent">{result.predicted_class}</Pill>
              </div>
              <div className="row">
                <span>Versión de modelo</span>
                <span className="mono">{result.model_version}</span>
              </div>

              <div style={{ marginTop: 12 }}>
                {ordered.map(([clase, prob]) => (
                  <div key={clase} style={{ marginBottom: 8 }}>
                    <div className="row" style={{ padding: '2px 0', border: 0 }}>
                      <span>{clase}</span>
                      <span className="mono">{pct(prob)}</span>
                    </div>
                    <div className="track">
                      <div className="fill" style={{ width: pct(prob) }} />
                    </div>
                  </div>
                ))}
              </div>

              <div className="form-actions">
                <button type="button" className="ghost" onClick={enviarAnotacion} disabled={sending}>
                  {sending ? 'Enviando…' : 'Enviar a cola de anotación'}
                </button>
              </div>
              {sent && (
                <div className="banner pass">
                  Enviado a la cola de anotación (imagen #{sent.image_id}, estado {sent.status}).
                </div>
              )}
            </>
          )}
        </Card>
      </div>
    </>
  );
}
