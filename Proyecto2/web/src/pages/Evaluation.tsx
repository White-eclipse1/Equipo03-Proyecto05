/**
 * Evaluation (P3): la evaluación única en el test congelado (F9 T21).
 *
 * Se bloquea hasta que exista la selección del candidato: si el backend
 * responde 409 (o 423) no se revela ninguna métrica de test (criterio 6.3).
 * Con evaluación: accuracy, F1 macro, matriz de confusión (filas=real,
 * columnas=predicho), métricas por clase y baseline de la clase mayoritaria.
 * La galería de aciertos/errores y la exportación del CSV llegan en el
 * siguiente slice de T21.
 */

import { useEffect, useState } from 'react';
import { Card, Pill, Tile } from '../components/ui';
import {
  ApiError,
  api,
  type EvalExample,
  type EvaluationExamples,
  type EvaluationReport,
  type ManifestMeta,
  type Selection,
} from '../lib/api';

const pct = (n: number): string => `${(n * 100).toFixed(1)}%`;

/**
 * Una fila de la galería: miniatura del recorte, real → predicho y probabilidad.
 *
 * La miniatura la sirve el backend (`/evaluation/crops/{crop_id}`). Si el recorte
 * falta (404), `onError` muestra un aviso en lugar de una imagen rota (4.4). Los
 * errores de clasificación se resaltan con `crop-error`.
 */
function ExampleRow({ example }: { example: EvalExample }) {
  const hit = example.true === example.predicted;
  const [broken, setBroken] = useState(false);
  return (
    <div className={`crop-row row${hit ? '' : ' crop-error'}`}>
      <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
        {broken ? (
          <span className="crop-missing" title={example.crop_id}>
            sin recorte
          </span>
        ) : (
          <img
            className="crop-thumb"
            src={api.p3.evaluationCropUrl(example.crop_id)}
            alt={`${example.true} → ${example.predicted}`}
            width={44}
            height={44}
            loading="lazy"
            onError={() => setBroken(true)}
          />
        )}
        <span className="mono" style={{ fontSize: 12 }}>
          {example.crop_id}
        </span>
      </span>
      <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
        <Pill kind={hit ? 'pass' : 'fail'}>
          {example.true} → {example.predicted}
        </Pill>
        <span className="mono">{pct(example.probability)}</span>
      </span>
    </div>
  );
}

export default function Evaluation() {
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [examples, setExamples] = useState<EvaluationExamples | null>(null);
  // Procedencia del candidato (6.3): el hash del manifiesto y el checkpoint salen
  // de selection.json; el release, del manifiesto congelado. Son opcionales: si
  // no cargan, la página muestra igual las métricas.
  const [selection, setSelection] = useState<Selection | null>(null);
  const [manifest, setManifest] = useState<ManifestMeta | null>(null);
  const [blocked, setBlocked] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.p3
      .evaluation()
      .then(async (r) => {
        if (cancelled) return;
        setReport(r);
        // Procedencia (tolerante a fallo): candidato y manifiesto de la evaluación.
        api.p3
          .selection()
          .then((s) => !cancelled && setSelection(s))
          .catch(() => {});
        api.p3
          .manifest(r.manifest_id)
          .then((m) => !cancelled && setManifest(m))
          .catch(() => {});
        try {
          const ex = await api.p3.evaluationExamples();
          if (!cancelled) setExamples(ex);
        } catch {
          // La galería es opcional: si falla, la página muestra igual las métricas.
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        // 409/423: la selección no está cerrada -> bloqueado, sin revelar test.
        if (e instanceof ApiError && (e.status === 409 || e.status === 423)) {
          setBlocked(e.message);
        } else {
          setError(e instanceof Error ? e.message : 'Error desconocido');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const cm = report?.confusion_matrix;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Evaluation</h1>
          <p className="page-sub">
            Evaluación única en el test congelado. Se revela solo después de cerrar la
            selección del candidato.
          </p>
        </div>
        {report && (
          <Pill kind={report.passes_threshold ? 'pass' : 'fail'}>
            {report.passes_threshold ? 'supera' : 'no supera'} el umbral {pct(report.threshold)}
          </Pill>
        )}
      </div>

      {error && <div className="banner warn">{error}</div>}

      {blocked ? (
        <Card title="Evaluación bloqueada">
          <p className="state">
            {blocked}. El test no se revela hasta que exista la selección del modelo.
          </p>
        </Card>
      ) : report ? (
        <>
          <div className="tiles">
            <Tile value={pct(report.accuracy)} label="Accuracy" tone="a" />
            <Tile value={report.f1_macro.toFixed(3)} label="F1 macro" tone="b" />
            <Tile value={report.test_size} label="Recortes de test" tone="d" />
            <Tile value={pct(report.majority_baseline)} label="Baseline (mayoritaria)" tone="c" />
          </div>

          <Card
            title="Procedencia"
            hint="El candidato evaluado y de dónde sale: run de MLflow, manifiesto congelado, release y checkpoint con su hash."
          >
            <div className="row">
              <span>Run</span>
              <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
                <span className="mono" style={{ fontSize: 11 }} title={report.run_id}>
                  {report.run_id.slice(0, 12)}…
                </span>
                <a href="#/experiments">Ver en Experiments</a>
              </span>
            </div>
            <div className="row">
              <span>Manifiesto</span>
              <span className="mono" style={{ fontSize: 12 }}>
                {report.manifest_id}
              </span>
            </div>
            {selection && (
              <div className="row">
                <span>Hash del manifiesto</span>
                <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
                  {selection.manifest_hash.slice(0, 16)}…
                </span>
              </div>
            )}
            {manifest && (
              <div className="row">
                <span>Release</span>
                <span className="mono">{manifest.release.release_id}</span>
              </div>
            )}
            {selection && (
              <div className="row">
                <span>Checkpoint</span>
                <span
                  className="mono"
                  style={{ fontSize: 11, color: 'var(--muted)', wordBreak: 'break-all' }}
                  title={selection.checkpoint_uri}
                >
                  {selection.checkpoint_uri} · {selection.checkpoint_sha256.slice(0, 16)}…
                </span>
              </div>
            )}
          </Card>

          <div className="cols-2">
            <Card
              title="Matriz de confusión"
              hint="Filas = clase real, columnas = clase predicha."
            >
              {cm && (
                <table aria-label="Matriz de confusión">
                  <thead>
                    <tr>
                      <th>real \ predicho</th>
                      {cm.labels.map((label) => (
                        <th key={label} className="num">
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {cm.labels.map((label, i) => (
                      <tr key={label}>
                        <td>{label}</td>
                        {(cm.rows_true_cols_pred[i] ?? []).map((value, j) => (
                          <td
                            key={cm.labels[j]}
                            className="num mono"
                            style={i === j ? { fontWeight: 600, color: 'var(--pass)' } : undefined}
                          >
                            {value}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>

            <Card title="Por clase">
              <table>
                <thead>
                  <tr>
                    <th>clase</th>
                    <th className="num">precision</th>
                    <th className="num">recall</th>
                    <th className="num">f1</th>
                    <th className="num">support</th>
                  </tr>
                </thead>
                <tbody>
                  {report.per_class.map((row) => (
                    <tr key={row.class}>
                      <td>{row.class}</td>
                      <td className="num mono">{row.precision.toFixed(3)}</td>
                      <td className="num mono">{row.recall.toFixed(3)}</td>
                      <td className="num mono">{row.f1.toFixed(3)}</td>
                      <td className="num mono">{row.support}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="row" style={{ marginTop: 8 }}>
                <span>Clase mayoritaria: {report.majority_class}</span>
                <span className="mono">{pct(report.majority_baseline)}</span>
              </div>
            </Card>
          </div>

          <Card
            title="Aciertos y errores del test"
            hint="Ejemplos con su clase real, la predicha y la probabilidad. Para auditar, exporta el CSV completo."
            aside={
              <a href={api.p3.evaluationPredictionsUrl()} download>
                Exportar predictions_test.csv
              </a>
            }
          >
            {report.most_confused != null ? (
              <p className="hint" style={{ marginTop: 0 }}>
                {`Par más confundido: ${report.most_confused.true} → ${report.most_confused.predicted} ` +
                  `(${report.most_confused.count} ${report.most_confused.count === 1 ? 'caso' : 'casos'})`}
              </p>
            ) : (
              <p className="hint" style={{ marginTop: 0 }}>
                No hubo errores en el test.
              </p>
            )}
            {examples ? (
              <div className="cols-2">
                <div>
                  <h3>Aciertos</h3>
                  {examples.correct.map((ex) => (
                    <ExampleRow key={ex.crop_id} example={ex} />
                  ))}
                </div>
                <div>
                  <h3>Errores</h3>
                  {examples.errors.map((ex) => (
                    <ExampleRow key={ex.crop_id} example={ex} />
                  ))}
                </div>
              </div>
            ) : (
              <p className="state">Cargando ejemplos…</p>
            )}
          </Card>
        </>
      ) : (
        !error && <p className="state">Cargando evaluación…</p>
      )}
    </>
  );
}
