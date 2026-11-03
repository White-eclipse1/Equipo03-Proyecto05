/**
 * Botón para eliminar los casi-duplicados.
 *
 * Es la única acción de la app que modifica el dataset, así que la secuencia
 * es deliberadamente de tres pasos: pedir el plan, enseñar qué se va a
 * eliminar, y solo entonces ofrecer el botón que lo ejecuta. Nada se borra por
 * un clic accidental.
 *
 * Las imágenes no se destruyen: se mueven a cuarentena, así que un falso
 * positivo del pHash se deshace moviéndolas de vuelta.
 */

import { useState } from 'react';
import { api, ApiError, type DedupePlan, type DedupeResult } from '../lib/api';
import RefreshAction from './RefreshAction';
import { Card, Pill } from './ui';

type Fase =
  | { kind: 'inicio' }
  | { kind: 'cargando' }
  | { kind: 'plan'; plan: DedupePlan }
  | { kind: 'ejecutando'; plan: DedupePlan }
  | { kind: 'hecho'; result: DedupeResult }
  | { kind: 'error'; message: string };

export default function DedupeAction() {
  const [fase, setFase] = useState<Fase>({ kind: 'inicio' });

  function fallo(error: unknown) {
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

  async function pedirPlan() {
    setFase({ kind: 'cargando' });
    try {
      setFase({ kind: 'plan', plan: await api.duplicatesPlan() });
    } catch (error) {
      fallo(error);
    }
  }

  async function ejecutar(plan: DedupePlan) {
    setFase({ kind: 'ejecutando', plan });
    try {
      setFase({ kind: 'hecho', result: await api.duplicatesRemove() });
    } catch (error) {
      fallo(error);
    }
  }

  return (
    <Card
      title="Eliminar duplicados"
      aside={<Pill kind="warning">modifica el dataset</Pill>}
      hint="De cada grupo de copias sobrevive la que se subió primero. Las demás se mueven a cuarentena, no se borran."
    >
      {fase.kind === 'inicio' && (
        <button className="danger" onClick={() => void pedirPlan()}>
          Ver qué se eliminaría
        </button>
      )}

      {fase.kind === 'cargando' && <p className="state">Calculando…</p>}

      {(fase.kind === 'plan' || fase.kind === 'ejecutando') && (
        <>
          <div className="row">
            <span>Se eliminarían</span>
            <span className="mono">
              {fase.plan.remove_count} imágenes y {fase.plan.annotations_removed} cajas
            </span>
          </div>
          <div className="row">
            <span>Quedarían</span>
            <span className="mono">
              {fase.plan.kept} de {fase.plan.total_images}
            </span>
          </div>

          {fase.plan.sample.length > 0 && (
            <details style={{ marginTop: 10 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12.5, color: 'var(--muted)' }}>
                Ver una muestra de los archivos
              </summary>
              <div
                className="mono"
                style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8, lineHeight: 1.7 }}
              >
                {fase.plan.sample.map((nombre) => (
                  <div key={nombre} style={{ wordBreak: 'break-all' }}>
                    {nombre}
                  </div>
                ))}
              </div>
            </details>
          )}

          {fase.plan.remove_count === 0 ? (
            <div className="banner pass">No hay duplicados que eliminar.</div>
          ) : (
            <div style={{ display: 'flex', gap: 9, marginTop: 14, flexWrap: 'wrap' }}>
              <button
                className="danger"
                onClick={() => void ejecutar(fase.plan)}
                disabled={fase.kind === 'ejecutando'}
              >
                {fase.kind === 'ejecutando'
                  ? 'Eliminando…'
                  : `Eliminar ${fase.plan.remove_count} duplicados`}
              </button>
              <button
                className="ghost"
                onClick={() => setFase({ kind: 'inicio' })}
                disabled={fase.kind === 'ejecutando'}
              >
                Cancelar
              </button>
            </div>
          )}
        </>
      )}

      {fase.kind === 'hecho' && (
        <>
          <div className="row">
            <span>Eliminadas</span>
            <span className="mono">
              {fase.result.removed_images} imágenes, {fase.result.removed_annotations ?? 0} cajas
            </span>
          </div>
          <div className="row">
            <span>Quedan</span>
            <span className="mono">{fase.result.remaining_images ?? '—'}</span>
          </div>
          {fase.result.quarantine_dir && (
            <div className="row">
              <span>En cuarentena</span>
              <span className="mono">{fase.result.quarantine_dir}/</span>
            </div>
          )}

          {fase.result.stale_reports && (
            <>
              <div className="banner warn">
                El dataset cambió: los reportes que estás viendo ya no lo describen.
              </div>
              {/* El siguiente paso es un boton, no una lista de comandos: si la
                  app pudo eliminar, puede volver a medir. */}
              <div style={{ marginTop: 12 }}>
                <RefreshAction compact />
              </div>
            </>
          )}

          {fase.result.undo && (
            <p className="hint" style={{ marginTop: 12, marginBottom: 0 }}>
              {fase.result.undo}
            </p>
          )}
        </>
      )}

      {fase.kind === 'error' && (
        <>
          <div className="banner fail" style={{ marginTop: 0 }}>
            {fase.message}
          </div>
          <button className="ghost" style={{ marginTop: 12 }} onClick={() => void pedirPlan()}>
            Reintentar
          </button>
        </>
      )}
    </Card>
  );
}
