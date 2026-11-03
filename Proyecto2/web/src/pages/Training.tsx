/**
 * Training (P3): elegir un release aprobado, ver su procedencia y el split
 * 70/20/10, configurar los parámetros y lanzar/seguir un entrenamiento (T19).
 *
 * Selector de release aprobado y procedencia; generación del manifiesto 70/20/10
 * con conteos por clase y partición; formulario de configuración con validación
 * (TrainingConfigForm); y, tras lanzar, la vista de estado del trabajo, cuyo id
 * se persiste en localStorage para que recargar la página lo reconstruya.
 */

import { useEffect, useState } from 'react';
import JobStatusView from '../components/JobStatusView';
import TrainingConfigForm from '../components/TrainingConfigForm';
import { Card, Pill } from '../components/ui';
import {
  api,
  type ManifestCreated,
  type P3ReleaseDetail,
  type P3ReleaseSummary,
  type SplitName,
} from '../lib/api';
import { launchBlockReason } from '../lib/training-config';

const SPLITS: SplitName[] = ['train', 'val', 'test'];
/** Dónde se recuerda el trabajo en curso para sobrevivir a un recargado. */
const JOB_STORAGE_KEY = 'p3.training.jobId';

/** Suma los conteos de una clase en las tres particiones. */
function totalPorClase(counts: ManifestCreated['counts'], className: string): number {
  return SPLITS.reduce((acc, split) => acc + (counts.crops[split][className] ?? 0), 0);
}

export default function Training() {
  const [releases, setReleases] = useState<P3ReleaseSummary[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Manifiesto congelado elegido del release (F12): su semilla genera el split.
  const [manifestId, setManifestId] = useState<string | null>(null);
  const [provenance, setProvenance] = useState<P3ReleaseDetail | null>(null);
  const [manifest, setManifest] = useState<ManifestCreated | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Un recargado reconstruye el trabajo en curso desde el id guardado.
  const [launchedJobId, setLaunchedJobId] = useState<string | null>(() =>
    localStorage.getItem(JOB_STORAGE_KEY),
  );

  // Releases aprobados: la lista de la que se puede elegir.
  useEffect(() => {
    let cancelled = false;
    api.p3
      .releases(true)
      .then((res) => {
        if (cancelled) return;
        setReleases(res.releases);
        // Selecciona el primer release ENTRENABLE (no el primero a secas): los
        // no entrenables quedan deshabilitados en el selector.
        setSelectedId(
          (prev) =>
            prev ??
            res.releases.find((r) => r.trainable)?.release_id ??
            res.releases[0]?.release_id ??
            null,
        );
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Error desconocido');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Procedencia del release elegido. Cambiar de release descarta el manifiesto
  // anterior: pertenece a otro release.
  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    setProvenance(null);
    setManifest(null);
    api.p3
      .release(selectedId)
      .then((detail) => {
        if (!cancelled) setProvenance(detail);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Error desconocido');
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  async function generarManifiesto() {
    const chosen = selected?.manifests.find((m) => m.manifest_id === manifestId);
    if (!selectedId || !chosen) return;
    setGenerating(true);
    setError(null);
    try {
      setManifest(await api.p3.createManifest(selectedId, chosen.seed));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error desconocido');
    } finally {
      setGenerating(false);
    }
  }

  function handleLaunched(jobId: string) {
    localStorage.setItem(JOB_STORAGE_KEY, jobId);
    setLaunchedJobId(jobId);
  }

  /** Olvida el trabajo en curso para volver a configurar otro. */
  function clearJob() {
    localStorage.removeItem(JOB_STORAGE_KEY);
    setLaunchedJobId(null);
  }

  function onSelectRelease(releaseId: string) {
    // Cambiar de release descarta el trabajo en curso: es de otro manifiesto.
    clearJob();
    setSelectedId(releaseId);
  }

  function onSelectManifest(id: string) {
    // Otro manifiesto es otro split: descarta el generado y el trabajo en curso.
    clearJob();
    setManifest(null);
    setManifestId(id);
  }

  const selected = releases?.find((r) => r.release_id === selectedId) ?? null;
  const manifestOptions = selected?.manifests ?? [];

  // Al cambiar de release, el manifiesto por defecto es el primero (el del barrido).
  useEffect(() => {
    setManifestId(selected?.manifests[0]?.manifest_id ?? null);
  }, [selected]);
  const classNames = manifest ? Object.keys(manifest.counts.crops.train) : [];
  // Motivo por el que no se puede lanzar aún (compuerta o manifiesto sin congelar).
  const blockReason = selected
    ? launchBlockReason(selected.quality_status, manifest !== null)
    : null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Training</h1>
          <p className="page-sub">
            Elige un release aprobado, revisa su procedencia y el split 70/20/10,
            configura los parámetros y lanza un entrenamiento.
          </p>
        </div>
      </div>

      {error && <div className="banner warn">{error}</div>}

      <div className="cols-2">
        <Card title="Release aprobado" hint="Solo se listan los releases que pasaron la compuerta de calidad de P2.">
          {releases === null ? (
            <p className="state">Cargando releases…</p>
          ) : releases.length === 0 ? (
            <p className="state">No hay releases aprobados todavía.</p>
          ) : (
            <>
              <label className="row" style={{ gap: 10 }}>
                <span>Release</span>
                <select
                  className="campo"
                  value={selectedId ?? ''}
                  onChange={(e) => onSelectRelease(e.target.value)}
                >
                  {releases.map((r) => (
                    <option key={r.release_id} value={r.release_id} disabled={!r.trainable}>
                      v{r.release_id} · {r.quality_status}
                      {!r.trainable && r.blocked_reason ? ` — ${r.blocked_reason}` : ''}
                    </option>
                  ))}
                </select>
              </label>

              {manifestOptions.length > 0 && (
                <label className="row" style={{ gap: 10 }}>
                  <span>Manifiesto</span>
                  <select
                    className="campo"
                    value={manifestId ?? ''}
                    onChange={(e) => onSelectManifest(e.target.value)}
                  >
                    {manifestOptions.map((m) => (
                      <option key={m.manifest_id} value={m.manifest_id}>
                        {m.manifest_id} · seed {m.seed}
                        {m.sweep ? ' · barrido' : ' · solo p3-pruebas'}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {selected && (
                <>
                  <div className="row">
                    <span>Huella del dataset</span>
                    <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
                      {selected.dataset_fingerprint.slice(0, 16)}…
                    </span>
                  </div>
                  <div className="row">
                    <span>Contenido</span>
                    <span className="mono" style={{ fontSize: 12 }}>
                      {selected.counts.images} img · {selected.counts.annotations} cajas
                    </span>
                  </div>
                </>
              )}
            </>
          )}
        </Card>

        <Card title="Procedencia" hint="Huellas que atan el release a su reporte de calidad y a su archivo.">
          {provenance === null ? (
            <p className="state">Selecciona un release para ver su procedencia.</p>
          ) : (
            <>
              <div className="row">
                <span>Reporte de calidad</span>
                <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
                  {provenance.quality_report_fingerprint.slice(0, 16)}…
                </span>
              </div>
              <div className="row">
                <span>Archivo (sha256)</span>
                <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
                  {provenance.archive_sha256
                    ? `${provenance.archive_sha256.slice(0, 16)}…`
                    : 'Sin hash registrado'}
                </span>
              </div>
              <div className="row">
                <span>Publicado en</span>
                <span style={{ display: 'inline-flex', gap: 4 }}>
                  {provenance.published_in.map((remote) => (
                    <Pill key={remote} kind="accent">
                      {remote.toUpperCase()}
                    </Pill>
                  ))}
                </span>
              </div>
            </>
          )}
        </Card>
      </div>

      <Card
        title="Manifiesto 70/20/10"
        hint="Se deriva del release aprobado: recorta las cajas COCO y reparte por grupos de duplicados sin fuga entre particiones."
        aside={
          <button
            type="button"
            className="ghost"
            onClick={generarManifiesto}
            disabled={!selectedId || generating}
          >
            {generating ? 'Generando…' : 'Generar manifiesto 70/20/10'}
          </button>
        }
      >
        {manifest === null ? (
          <p className="state">
            Aún no hay manifiesto para este release. Genéralo para ver los conteos por clase y
            partición.
          </p>
        ) : (
          <>
            <div className="row">
              <span>Manifiesto</span>
              <span className="mono" style={{ fontSize: 12 }}>
                {manifest.manifest_id}
              </span>
            </div>
            <table>
              <thead>
                <tr>
                  <th>Clase</th>
                  {SPLITS.map((split) => (
                    <th key={split} className="num">
                      {split}
                    </th>
                  ))}
                  <th className="num">total</th>
                </tr>
              </thead>
              <tbody>
                {classNames.map((className) => (
                  <tr key={className}>
                    <td>{className}</td>
                    {SPLITS.map((split) => (
                      <td key={split} className="num mono">
                        {manifest.counts.crops[split][className] ?? 0}
                      </td>
                    ))}
                    <td className="num mono">{totalPorClase(manifest.counts, className)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Card>

      {launchedJobId ? (
        <Card
          title="Entrenamiento"
          hint="Estado, avance, logs y error del trabajo. Se conserva al recargar la página."
          aside={
            <button type="button" className="ghost" onClick={clearJob}>
              Configurar otro
            </button>
          }
        >
          <JobStatusView jobId={launchedJobId} />
        </Card>
      ) : selected ? (
        <Card
          title="Configuración y lanzamiento"
          hint="Los rangos válidos son los de contratos.md §3; un valor fuera de rango se avisa junto al campo y bloquea el lanzamiento."
        >
          {blockReason || !manifest ? (
            <p className="state">
              {blockReason ?? 'Genera el manifiesto 70/20/10 antes de lanzar un entrenamiento.'}
            </p>
          ) : (
            <TrainingConfigForm
              manifestId={manifest.manifest_id}
              sweep={manifestOptions.find((m) => m.manifest_id === manifest.manifest_id)?.sweep ?? true}
              onLaunched={handleLaunched}
            />
          )}
        </Card>
      ) : null}
    </>
  );
}
