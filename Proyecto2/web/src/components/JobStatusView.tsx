/**
 * Vista de estado de un trabajo de entrenamiento (F8 T19).
 *
 * Consulta `GET /training/jobs/{id}` al montar y hace polling mientras el
 * trabajo sigue activo (queued/running). Muestra estado, avance, logs y error.
 * El estado vive en el servidor: recargar la página y volver a consultar el
 * mismo id reconstruye la vista (la persistencia del id la hace la página).
 */

import { useEffect, useState } from 'react';
import { api, type TrainingJob } from '../lib/api';
import { Pill } from './ui';

const POLL_MS = 1500;
const ACTIVE_STATES = ['queued', 'running'];

const toneFor = (status: string): string =>
  status === 'succeeded' ? 'pass' : status === 'failed' ? 'fail' : 'accent';

export default function JobStatusView({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<TrainingJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function tick() {
      try {
        const fetched = await api.p3.trainingJob(jobId);
        if (cancelled) return;
        setJob(fetched);
        setError(null);
        if (ACTIVE_STATES.includes(fetched.status)) timer = setTimeout(tick, POLL_MS);
      } catch (e: unknown) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Error desconocido');
        timer = setTimeout(tick, POLL_MS);
      }
    }

    setJob(null);
    setError(null);
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  if (!job) {
    return error ? (
      <div className="banner warn">
        No se pudo cargar el trabajo <span className="mono">{jobId}</span>: {error}
      </div>
    ) : (
      <p className="state">Cargando trabajo…</p>
    );
  }

  const pct = Math.round((job.progress ?? 0) * 100);

  return (
    <>
      <div className="row">
        <span>Estado</span>
        <Pill kind={toneFor(job.status)}>{job.status}</Pill>
      </div>
      <div className="row">
        <span>Trabajo</span>
        <span className="mono" style={{ fontSize: 12 }}>
          {job.job_id}
        </span>
      </div>
      {job.mlflow_run_id && (
        <div className="row">
          <span>MLflow run</span>
          <span className="mono" style={{ fontSize: 12 }}>
            {job.mlflow_run_id}
          </span>
        </div>
      )}
      <div className="row">
        <span>Avance</span>
        <span className="mono">{pct}%</span>
      </div>
      <progress value={pct} max={100} style={{ width: '100%' }} />

      {job.error && <div className="banner warn">{job.error}</div>}

      <details open>
        <summary>Logs ({job.logs.length})</summary>
        <pre
          className="mono"
          style={{ fontSize: 11.5, whiteSpace: 'pre-wrap', margin: '8px 0 0', color: 'var(--ink-2)' }}
        >
          {job.logs.join('\n')}
        </pre>
      </details>
    </>
  );
}
