/**
 * Botón para recalcular el pipeline sin salir de la app.
 *
 * Los artefactos que pinta esta interfaz los produce el pipeline, y cualquier
 * cambio en el dataset los deja obsoletos. Antes de esto la única salida era
 * abrir una terminal: una app que puede modificar el dataset pero no volver a
 * medirlo deja a quien la usa a medio camino.
 *
 * A diferencia del botón de duplicados, este NO modifica el dataset: solo
 * vuelve a leerlo y reescribe los reportes. Por eso no pide confirmación.
 */

import { useState } from 'react';
import { api, ApiError, type RefreshResult } from '../lib/api';
import { Card, Pill } from './ui';

type Fase =
  | { kind: 'inicio' }
  | { kind: 'corriendo' }
  | { kind: 'hecho'; result: RefreshResult }
  | { kind: 'error'; message: string };

export default function RefreshAction({
  compact = false,
  onDone,
}: {
  /** Sin tarjeta alrededor: para incrustarlo dentro de otra. */
  compact?: boolean;
  onDone?: () => void;
}) {
  const [fase, setFase] = useState<Fase>({ kind: 'inicio' });

  async function correr() {
    setFase({ kind: 'corriendo' });
    try {
      const result = await api.pipelineRefresh();
      setFase({ kind: 'hecho', result });
      onDone?.();
    } catch (error) {
      setFase({
        kind: 'error',
        message:
          error instanceof ApiError
            ? error.message
            : error instanceof Error
              ? error.message
              : 'Error desconocido',
      });
    }
  }

  const cuerpo = (
    <>
      {(fase.kind === 'inicio' || fase.kind === 'corriendo') && (
        <>
          <button className="ghost" onClick={() => void correr()} disabled={fase.kind === 'corriendo'}>
            {fase.kind === 'corriendo' ? 'Recalculando…' : 'Recalcular ahora'}
          </button>
          {fase.kind === 'corriendo' && (
            <p className="hint" style={{ marginTop: 10, marginBottom: 0 }}>
              Los seis analizadores recorren todas las imágenes. Tarda unos segundos.
            </p>
          )}
        </>
      )}

      {fase.kind === 'hecho' && (
        <>
          <div className="row">
            <span>Veredicto</span>
            <Pill kind={fase.result.status === 'pass' ? 'pass' : 'fail'}>
              {fase.result.status === 'pass' ? 'pasa' : 'bloquea'}
            </Pill>
          </div>
          <div className="row">
            <span>Dataset medido</span>
            <span className="mono">
              {fase.result.totals.images} imágenes, {fase.result.totals.annotations} cajas
            </span>
          </div>
          <div className="row">
            <span>Tardó</span>
            <span className="mono">{fase.result.duration_seconds}s</span>
          </div>

          {fase.result.blocking.length > 0 && (
            <div className="banner fail">
              Bloquean la publicación: {fase.result.blocking.join(', ')}
            </div>
          )}
          {fase.result.blocking.length === 0 && (
            <div className="banner pass">Ningún check bloquea. El dataset se puede publicar.</div>
          )}
          {fase.result.warnings.length > 0 && (
            <div className="banner warn">Solo avisan: {fase.result.warnings.join(', ')}</div>
          )}

          <p className="hint" style={{ marginTop: 12, marginBottom: 0 }}>
            {/* DVC no se toca desde aquí: mueve bytes a un remoto con
                credenciales y queda registrado en el versionado. */}
            Los reportes ya están al día. Para versionar el dataset en DVC:{' '}
            <span className="mono">dvc add data/raw &amp;&amp; dvc push</span>
          </p>

          <button className="ghost" style={{ marginTop: 12 }} onClick={() => window.location.reload()}>
            Recargar la vista
          </button>
        </>
      )}

      {fase.kind === 'error' && (
        <>
          <div className="banner fail" style={{ marginTop: 0 }}>
            {fase.message}
          </div>
          <button className="ghost" style={{ marginTop: 12 }} onClick={() => void correr()}>
            Reintentar
          </button>
        </>
      )}
    </>
  );

  if (compact) return cuerpo;

  return (
    <Card
      title="Recalcular el pipeline"
      aside={<Pill kind="accent">no modifica el dataset</Pill>}
      hint="Vuelve a correr los analizadores y la compuerta sobre lo que hay en disco, y reescribe quality.json y stats.json. Equivale a `dq analyze` y `dq gate`, pero en una sola pasada."
    >
      {cuerpo}
    </Card>
  );
}
