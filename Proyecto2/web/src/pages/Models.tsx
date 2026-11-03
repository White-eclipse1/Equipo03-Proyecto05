/**
 * Models (P3): versiones de modelo publicadas y la versión activa (F9 T22).
 *
 * Lista cada versión (semver del MODELO, distinta del release del dataset) con
 * su run, manifiesto, SHA-256 y estado en S3, la tarjeta (MODEL_CARD.md) y una
 * acción "Usar para inferencia" que llama a `POST /models/{version}/activate`.
 * El backend verifica el objeto en S3 antes de aceptar; si no existe, responde
 * 409 y aquí se muestra el motivo sin cambiar la activa.
 */

import { useEffect, useState } from 'react';
import { Card, Pill } from '../components/ui';
import { ApiError, api, type ModelEntry } from '../lib/api';

const short = (s: string): string => (s.length > 12 ? `${s.slice(0, 12)}…` : s);

export default function Models() {
  const [models, setModels] = useState<ModelEntry[] | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [activating, setActivating] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.p3
      .models()
      .then((res) => {
        if (cancelled) return;
        setModels(res.models);
        setActive(res.active_version);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        // 503 (fix #17): el backend no puede acceder a S3 (sin credenciales o el
        // servicio caído). No es un error de la UI: se muestra como "no disponible".
        if (e instanceof ApiError && e.status === 503) {
          setUnavailable(e.message);
        } else {
          setError(e instanceof Error ? e.message : 'Error desconocido');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function activar(version: string) {
    setActivating(version);
    setActionError(null);
    try {
      const { active_version } = await api.p3.activateModel(version);
      setActive(active_version);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Error desconocido');
    } finally {
      setActivating(null);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Models</h1>
          <p className="page-sub">
            Versiones de modelo publicadas en S3 (versión del modelo, no del dataset). Elige
            cuál usa la inferencia.
          </p>
        </div>
        {active && <Pill kind="accent">Versión activa: {active}</Pill>}
      </div>

      {error && <div className="banner warn">{error}</div>}
      {actionError && <div className="banner warn">{actionError}</div>}

      <Card title="Versiones publicadas">
        {unavailable ? (
          <p className="state">
            Servicio de modelos no disponible ({unavailable}). No hay versiones que mostrar
            hasta que el backend tenga acceso a S3.
          </p>
        ) : models === null ? (
          <p className="state">Cargando versiones…</p>
        ) : models.length === 0 ? (
          <p className="state">No hay versiones publicadas todavía.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>versión</th>
                <th>release (dataset)</th>
                <th>run</th>
                <th>sha256</th>
                <th>S3</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.version}>
                  <td>
                    <span>{m.version}</span>
                    {m.version === active && (
                      <>
                        {' '}
                        <Pill kind="pass">activa</Pill>
                      </>
                    )}
                  </td>
                  <td className="mono">{m.release_id}</td>
                  <td className="mono" title={m.run_id}>
                    {short(m.run_id)}
                  </td>
                  <td className="mono" style={{ fontSize: 11 }}>
                    <div title={m.s3.sha256}>{short(m.s3.sha256)}</div>
                    {m.s3.exists && (
                      <a href={api.p3.modelWeightsUrl(m.version)} download>
                        Descargar pesos
                      </a>
                    )}
                  </td>
                  <td>
                    <Pill kind={m.s3.exists ? 'pass' : 'fail'}>
                      {m.s3.exists ? 'existe' : 'ausente'}
                    </Pill>
                  </td>
                  <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                    <a href={api.p3.modelCardUrl(m.version)} target="_blank" rel="noreferrer">
                      tarjeta
                    </a>
                    {m.version !== active && (
                      <>
                        {' · '}
                        <button
                          type="button"
                          className="ghost"
                          disabled={activating !== null}
                          onClick={() => activar(m.version)}
                        >
                          {activating === m.version
                            ? 'Activando…'
                            : `Usar ${m.version} para inferencia`}
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
