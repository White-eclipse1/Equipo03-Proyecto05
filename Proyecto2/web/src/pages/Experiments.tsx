/**
 * Experiments (P3): las corridas reales de MLflow, con filtros, orden,
 * comparación y curvas (T20).
 *
 * Tabla ordenable/filtrable por parámetros y métricas de validación; selección
 * de 2+ corridas para comparar parámetros; panel de detalle con curvas train/val
 * de loss y accuracy por época y enlace al run en MLflow con el mismo run_id; y
 * la tarjeta del candidato seleccionado (`selection.json`), sin métricas de test.
 */

import { useEffect, useMemo, useState } from 'react';
import { LineChart, seriesColor } from '../components/charts';
import { Card, Pill } from '../components/ui';
import { api, type Config, type RunDetail, type RunSummary, type Selection } from '../lib/api';

/** Métricas por las que se puede ordenar la tabla. */
type SortKey = 'best_val_accuracy' | 'best_val_loss' | 'best_epoch';

/**
 * Base de la UI de MLflow para enlazar a un run, SIN hornear el puerto 5000:
 *  1. `VITE_MLFLOW_URL` en tiempo de build (si el despliegue la fija ahí),
 *  2. `mlflow_url` de `/api/config` en tiempo de ejecución (el preferido: el
 *     despliegue la cambia sin recompilar el portal),
 *  3. `http://localhost:5000` solo como comodín de desarrollo local.
 */
const MLFLOW_URL_BUILD: string | undefined = import.meta.env.VITE_MLFLOW_URL;
const MLFLOW_URL_DEV_FALLBACK = 'http://localhost:5000';
const mlflowRunUrl = (base: string, experimentId: string, runId: string): string =>
  `${base.replace(/\/$/, '')}/#/experiments/${experimentId}/runs/${runId}`;

const fmt = (n: number): string => n.toFixed(3);
const shortId = (id: string): string => id.slice(0, 8);

export default function Experiments() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('best_val_accuracy');
  const [desc, setDesc] = useState(true);
  const [compareIds, setCompareIds] = useState<Set<string>>(() => new Set());
  const [openRunId, setOpenRunId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  // Base de la UI de MLflow: build-time si existe, si no la de /api/config.
  const [mlflowBase, setMlflowBase] = useState<string>(MLFLOW_URL_BUILD ?? '');

  useEffect(() => {
    let cancelled = false;
    api.p3
      .runs({ status: 'FINISHED', order_by: 'val_accuracy', desc: true })
      .then((res) => {
        if (!cancelled) setRuns(res.runs);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Error desconocido');
      });
    // Sin override de build, el despliegue dice dónde está MLflow en /api/config.
    if (!MLFLOW_URL_BUILD) {
      api
        .config()
        .then((c: Config) => !cancelled && c.mlflow_url && setMlflowBase(c.mlflow_url))
        .catch(() => {});
    }
    // La selección puede no existir aún (menos de 10 corridas): no es un error.
    api.p3
      .selection()
      .then((s) => {
        if (!cancelled) setSelection(s);
      })
      .catch(() => {
        /* sin candidato todavía */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const shown = useMemo(() => {
    if (!runs) return [];
    const needle = filter.trim().toLowerCase();
    const filtered = needle
      ? runs.filter(
          (r) =>
            r.run_id.toLowerCase().includes(needle) ||
            JSON.stringify(r.params).toLowerCase().includes(needle),
        )
      : runs;
    return [...filtered].sort((a, b) => (desc ? b[sortKey] - a[sortKey] : a[sortKey] - b[sortKey]));
  }, [runs, filter, sortKey, desc]);

  // Detalle de la corrida abierta: curvas y artefactos desde GET /runs/{id}.
  useEffect(() => {
    if (!openRunId) return;
    let cancelled = false;
    setDetail(null);
    setDetailError(null);
    api.p3
      .run(openRunId)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e: unknown) => {
        if (!cancelled) setDetailError(e instanceof Error ? e.message : 'Error desconocido');
      });
    return () => {
      cancelled = true;
    };
  }, [openRunId]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setDesc((d) => !d);
    } else {
      setSortKey(key);
      setDesc(true);
    }
  }

  function toggleCompare(runId: string) {
    setCompareIds((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });
  }

  const arrow = (key: SortKey) => (key === sortKey ? (desc ? ' ▼' : ' ▲') : '');

  // Corridas elegidas para comparar y las claves de parámetros a enfrentar.
  const compared = (runs ?? []).filter((r) => compareIds.has(r.run_id));
  const paramKeys = [...new Set(compared.flatMap((r) => Object.keys(r.params)))];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Experiments</h1>
          <p className="page-sub">
            Corridas de MLflow con filtros por parámetros y métricas de validación,
            comparación de corridas y curvas de entrenamiento.
          </p>
        </div>
        {runs && <Pill kind="accent">{runs.length} corridas</Pill>}
      </div>

      {error && <div className="banner warn">{error}</div>}

      {selection && (
        <Card
          title="Candidato seleccionado"
          hint="Elegido por validación (selection.json). Las métricas de test no se muestran aquí: se revelan solo en Evaluation, tras cerrar la selección."
        >
          <div className="row">
            <span>Corrida</span>
            <span className="mono" style={{ fontSize: 12 }}>
              {selection.run_id}
            </span>
          </div>
          <div className="row">
            <span>Regla</span>
            <span style={{ fontSize: 12 }}>{selection.rule}</span>
          </div>
          <div className="row">
            <span>val_accuracy · val_loss</span>
            <span className="mono">
              {fmt(selection.val_accuracy)} · {fmt(selection.val_loss)}
            </span>
          </div>
          <div className="row">
            <span>Mejor época · corridas evaluadas</span>
            <span className="mono">
              {selection.best_epoch} · {selection.candidates}
            </span>
          </div>
        </Card>
      )}

      <Card title="Corridas">
        <label className="row" style={{ gap: 10 }}>
          <span>Filtrar</span>
          <input
            className="campo"
            type="search"
            placeholder="optimizer, run_id, learning_rate…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </label>

        {runs === null ? (
          <p className="state">Cargando corridas…</p>
        ) : shown.length === 0 ? (
          <p className="state">Ninguna corrida coincide con el filtro.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th aria-label="comparar" />
                <th>run</th>
                <th>optimizer</th>
                <th className="num">batch</th>
                <th className="num">lr</th>
                <th className="num sort-th">
                  <button type="button" onClick={() => toggleSort('best_val_accuracy')}>
                    val_acc{arrow('best_val_accuracy')}
                  </button>
                </th>
                <th className="num sort-th">
                  <button type="button" onClick={() => toggleSort('best_val_loss')}>
                    val_loss{arrow('best_val_loss')}
                  </button>
                </th>
                <th className="num sort-th">
                  <button type="button" onClick={() => toggleSort('best_epoch')}>
                    época{arrow('best_epoch')}
                  </button>
                </th>
                <th>estado</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shown.map((run) => (
                <tr key={run.run_id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`comparar ${shortId(run.run_id)}`}
                      checked={compareIds.has(run.run_id)}
                      onChange={() => toggleCompare(run.run_id)}
                    />
                  </td>
                  <td className="mono" title={run.run_id}>
                    {shortId(run.run_id)}
                  </td>
                  <td>{run.params.optimizer}</td>
                  <td className="num mono">{run.params.batch_size}</td>
                  <td className="num mono">{run.params.learning_rate}</td>
                  <td className="num mono">{fmt(run.best_val_accuracy)}</td>
                  <td className="num mono">{fmt(run.best_val_loss)}</td>
                  <td className="num mono">{run.best_epoch}</td>
                  <td>
                    <Pill kind={run.status === 'FINISHED' ? 'pass' : 'muted'}>{run.status}</Pill>
                  </td>
                  <td>
                    <button type="button" className="ghost" onClick={() => setOpenRunId(run.run_id)}>
                      Detalle
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {compared.length >= 2 && (
        <Card title={`Comparación de ${compared.length} corridas`}>
          <table aria-label="Comparación de corridas">
            <thead>
              <tr>
                <th>parámetro</th>
                {compared.map((run) => (
                  <th key={run.run_id} className="mono">
                    {shortId(run.run_id)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {paramKeys.map((key) => (
                <tr key={key}>
                  <td>{key}</td>
                  {compared.map((run) => (
                    <td key={run.run_id} className="mono">
                      {run.params[key] ?? '—'}
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <td>val_accuracy</td>
                {compared.map((run) => (
                  <td key={run.run_id} className="mono">
                    {fmt(run.best_val_accuracy)}
                  </td>
                ))}
              </tr>
              <tr>
                <td>val_loss</td>
                {compared.map((run) => (
                  <td key={run.run_id} className="mono">
                    {fmt(run.best_val_loss)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </Card>
      )}

      {openRunId && (
        <Card
          title="Detalle de la corrida"
          hint={openRunId}
          aside={
            <button type="button" className="ghost" onClick={() => setOpenRunId(null)}>
              Cerrar
            </button>
          }
        >
          <div className="row">
            <span>MLflow</span>
            <a
              href={mlflowRunUrl(
                mlflowBase || MLFLOW_URL_DEV_FALLBACK,
                detail?.experiment_id ?? runs?.find((r) => r.run_id === openRunId)?.experiment_id ?? '0',
                openRunId,
              )}
              target="_blank"
              rel="noreferrer"
            >
              Abrir en MLflow ({shortId(openRunId)})
            </a>
          </div>

          {detailError ? (
            <div className="banner warn">{detailError}</div>
          ) : detail === null ? (
            <p className="state">Cargando curvas…</p>
          ) : (
            <>
              <h3>Loss</h3>
              <LineChart
                title="Curvas de loss (train/val) por época"
                series={[
                  { label: 'train_loss', color: seriesColor(0), values: detail.history.map((h) => h.train_loss) },
                  { label: 'val_loss', color: seriesColor(1), values: detail.history.map((h) => h.val_loss) },
                ]}
              />
              <h3>Accuracy</h3>
              <LineChart
                title="Curvas de accuracy (train/val) por época"
                series={[
                  { label: 'train_accuracy', color: seriesColor(0), values: detail.history.map((h) => h.train_accuracy) },
                  { label: 'val_accuracy', color: seriesColor(1), values: detail.history.map((h) => h.val_accuracy) },
                ]}
              />
              <div style={{ marginTop: 12, display: 'flex', gap: 14, fontSize: 11.5, color: 'var(--ink-2)' }}>
                <span>
                  <span className="dot" style={{ background: seriesColor(0) }} /> train
                </span>
                <span>
                  <span className="dot" style={{ background: seriesColor(1) }} /> val
                </span>
              </div>

              <h3>Artefactos</h3>
              {Object.entries(detail.artifacts).map(([name, uri]) => (
                <div className="row" key={name}>
                  <span>{name}</span>
                  <span className="mono" style={{ fontSize: 11, color: 'var(--muted)', wordBreak: 'break-all' }}>
                    {uri}
                  </span>
                </div>
              ))}
            </>
          )}
        </Card>
      )}
    </>
  );
}
