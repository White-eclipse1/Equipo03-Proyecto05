/**
 * Capturas Edge (P4): fotos clasificadas en el dispositivo y guardadas en el almacén.
 *
 * Lee solo `/api/p4/capturas` (sin datos fijos). Orden: el del backend, de más
 * reciente a más antigua por `captured_at` en UTC. Se actualiza con el botón o
 * cada 30 s mientras la pestaña está visible. Si una actualización falla, se
 * conserva la última lista y se avisa: el error no borra lo que ya se veía.
 */

import { useCallback, useEffect, useState } from 'react';
import { Card, Pill } from '../components/ui';
import { ApiError, api, type CapturaEdge, type CapturasRespuesta } from '../lib/api';

const INTERVALO_MS = 30_000;

/** `2026-10-15T10:00:00-06:00` → `2026-10-15 10:00:00 (UTC-06:00)`, con la zona del dispositivo. */
export function fechaConZona(iso: string): string {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}(?::\d{2})?)(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/.exec(iso);
  if (!m) return iso;
  const zona = m[3] === 'Z' || m[3] === '+00:00' ? 'UTC' : `UTC${m[3]}`;
  return `${m[1]} ${m[2]} (${zona})`;
}

const corto = (sha: string): string => `${sha.slice(0, 10)}…`;

function Region({ captura }: { captura: CapturaEdge }) {
  const r = captura.region;
  if (!r) return null;
  const pct = (valor: number, total: number) => `${(valor / total) * 100}%`;
  return (
    <div
      className="cap-region"
      data-testid="region"
      style={{
        left: pct(r.x, captura.image_width),
        top: pct(r.y, captura.image_height),
        width: pct(r.width, captura.image_width),
        height: pct(r.height, captura.image_height),
      }}
    />
  );
}

function Tarjeta({ captura }: { captura: CapturaEdge }) {
  const [sinFoto, setSinFoto] = useState(false);
  return (
    <article className="cap-card" aria-label={`Captura ${captura.capture_id}`}>
      <div
        className="cap-foto"
        style={{ aspectRatio: `${captura.image_width} / ${captura.image_height}` }}
      >
        {sinFoto ? (
          <p className="cap-sin-foto">No se pudo cargar la foto</p>
        ) : (
          <img
            src={api.p4.fotoUrl(captura.capture_id)}
            alt={`Foto de la captura ${captura.capture_id}`}
            loading="lazy"
            onError={() => setSinFoto(true)}
          />
        )}
        <Region captura={captura} />
      </div>
      <div className="cap-datos">
        <div className="cap-clase">
          <Pill kind="accent">{captura.predicted_class}</Pill>
          <span title={String(captura.confidence)}>
            {(captura.confidence * 100).toFixed(1)} %
          </span>
        </div>
        <dl>
          <dt>ID</dt>
          <dd className="mono">{captura.capture_id}</dd>
          <dt>Capturada</dt>
          <dd>{fechaConZona(captura.captured_at)}</dd>
          <dt>Recibida</dt>
          <dd>{fechaConZona(captura.received_at)}</dd>
          <dt>Dispositivo</dt>
          <dd className="mono">{captura.device_id}</dd>
          <dt>Modelo</dt>
          <dd>
            <span className="mono">{captura.model_version}</span>{' '}
            <span className="mono cap-tenue" title={captura.model_sha256}>
              {corto(captura.model_sha256)}
            </span>
          </dd>
          {captura.region && (
            <>
              <dt>Recorte</dt>
              <dd className="mono">
                {captura.region.x},{captura.region.y} · {captura.region.width}×
                {captura.region.height}
              </dd>
            </>
          )}
        </dl>
      </div>
    </article>
  );
}

export default function CapturasEdge() {
  const [datos, setDatos] = useState<CapturasRespuesta | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [noDisponible, setNoDisponible] = useState<string | null>(null);
  const [actualizada, setActualizada] = useState<Date | null>(null);
  const [auto, setAuto] = useState(true);

  const cargar = useCallback(async () => {
    setCargando(true);
    try {
      const respuesta = await api.p4.capturas();
      setDatos(respuesta);
      setError(null);
      setNoDisponible(null);
      setActualizada(new Date());
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 503) {
        setNoDisponible(e.message);
        setError(null);
      } else {
        setError(e instanceof Error ? e.message : 'Error desconocido');
        setNoDisponible(null);
      }
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  useEffect(() => {
    if (!auto) return undefined;
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') void cargar();
    }, INTERVALO_MS);
    return () => window.clearInterval(id);
  }, [auto, cargar]);

  const primeraCarga = datos === null && cargando;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Capturas Edge</h1>
          <p className="page-sub">
            Fotos tomadas y clasificadas en el dispositivo edge, guardadas en el almacén con sus
            metadatos. De la más reciente a la más antigua.
          </p>
        </div>
        <div className="cap-acciones">
          <button type="button" className="ghost" onClick={() => void cargar()} disabled={cargando}>
            {cargando ? 'Actualizando…' : 'Actualizar'}
          </button>
          <label className="cap-auto">
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
            cada 30 s
          </label>
          <a href={api.p4.exportarUrl('csv')}>CSV</a>
          <a href={api.p4.exportarUrl('json')}>JSON</a>
        </div>
      </div>

      {/* Una falla al actualizar (incluido un 503) avisa y conserva la última lista. */}
      {datos !== null && (error || noDisponible) && (
        <div className="banner warn" role="alert">
          No se pudo actualizar: {error ?? noDisponible}. Se muestra la última lista cargada.
        </div>
      )}
      {datos && datos.errores.length > 0 && (
        <div className="banner warn">
          {datos.errores.length} registro(s) no se pudieron leer:{' '}
          <span className="mono">{datos.errores.map((e) => e.llave).join(', ')}</span>
        </div>
      )}

      <Card
        title={datos ? `${datos.total} captura(s)` : 'Capturas'}
        aside={
          actualizada && (
            <span className="cap-tenue">Actualizada {actualizada.toLocaleTimeString()}</span>
          )
        }
      >
        {primeraCarga ? (
          <p className="state">Cargando capturas…</p>
        ) : datos === null && noDisponible ? (
          <p className="state">
            Capturas no disponibles: {noDisponible}. Revisa la configuración del receptor (P4_*).
          </p>
        ) : datos === null ? (
          <div className="state" role="alert">
            <p>No se pudieron cargar las capturas.</p>
            {error && <p className="mono">{error}</p>}
          </div>
        ) : datos.items.length === 0 ? (
          <p className="state">
            Todavía no hay capturas. Aparecerán aquí en cuanto el dispositivo envíe la primera.
          </p>
        ) : (
          <div className="cap-grid">
            {datos.items.map((captura) => (
              <Tarjeta key={captura.capture_id} captura={captura} />
            ))}
          </div>
        )}
      </Card>
    </>
  );
}
