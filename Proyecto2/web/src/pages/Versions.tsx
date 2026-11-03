/** Versions: el historial inmutable de releases. */

import { Card, Pill, Resolve, useApi } from '../components/ui';
import { api, type RemotePublication } from '../lib/api';
import { MIN_IMAGES, qualityDiff } from '../lib/version-diff';

/** Los remotes conocidos, en el orden en que un release los recorre. */
const REMOTES = ['dev', 'prod'] as const;

/** En qué remotes está publicada una versión. Gris = todavía no está ahí. */
function Remotes({ publicados }: { publicados: RemotePublication[] }) {
  const porNombre = new Map(publicados.map((p) => [p.remote, p]));
  // Un remote con nombre propio (ni dev ni prod) se enseña igual: el registro
  // no impone la lista, solo la ordena.
  const extra = publicados.filter((p) => !REMOTES.includes(p.remote as (typeof REMOTES)[number]));

  return (
    <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
      {REMOTES.map((nombre) => {
        const publicado = porNombre.get(nombre);
        return (
          <Pill key={nombre} kind={publicado ? 'pass' : 'muted'}>
            <span title={publicado ? publicado.storage_uri : `no publicada en ${nombre}`}>
              {nombre.toUpperCase()}
            </span>
          </Pill>
        );
      })}
      {extra.map((p) => (
        <Pill key={p.remote} kind="accent">
          <span title={p.storage_uri}>{p.remote.toUpperCase()}</span>
        </Pill>
      ))}
    </span>
  );
}

function Delta({ actual, previo }: { actual: number; previo: number }) {
  const diferencia = actual - previo;
  const color = diferencia > 0 ? 'var(--pass)' : diferencia < 0 ? 'var(--fail)' : 'var(--muted)';
  return (
    <span className="mono" style={{ color }}>
      {diferencia > 0 ? '+' : ''}
      {diferencia.toLocaleString('es')}
    </span>
  );
}

export default function Versions() {
  const state = useApi(() => api.versions());

  return (
    <Resolve state={state}>
      {(envelope) => {
        // El manifiesto viene en orden ascendente; la más reciente va arriba.
        const versions = [...envelope.data.versions].reverse();
        const ultima = versions[0];
        const previa = versions[1];
        const diff = ultima && previa ? qualityDiff(previa, ultima) : null;

        return (
          <>
            <div className="page-head">
              <div>
                <h1>Versions</h1>
                <p className="page-sub">
                  Cada versión se identifica por la huella de su contenido. Una versión publicada
                  no se edita nunca: un cambio produce una versión nueva.
                </p>
              </div>
              <Pill kind="accent">
                {versions.length} {versions.length === 1 ? 'versión' : 'versiones'}
              </Pill>
            </div>

            <div className="cols-2">
              <Card title="Historial">
                {versions.length === 0 ? (
                  <p className="state">
                    Todavía no hay ninguna versión. Corre <code>dq release</code>.
                  </p>
                ) : (
                  versions.map((version) => (
                    <div className="row" key={version.version}>
                      <div className="row-main">
                        <Pill kind={version.quality_status === 'pass' ? 'pass' : 'fail'}>
                          v{version.version}
                        </Pill>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 12.5 }}>{version.notes ?? 'sin notas'}</div>
                          <div className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
                            {version.created_at.slice(0, 10)} ·{' '}
                            {version.dataset_fingerprint.slice(0, 12)}…
                          </div>
                        </div>
                      </div>
                      <div style={{ textAlign: 'right', flex: 'none' }}>
                        <Remotes publicados={version.published_in ?? []} />
                        <div className="mono" style={{ fontSize: 12, marginTop: 4 }}>
                          {version.counts.images} img
                        </div>
                        <div className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
                          {version.counts.annotations} cajas
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </Card>

              <div className="grid">
                {ultima && previa && (
                  <Card title="Diff" hint={`v${previa.version} → v${ultima.version}`}>
                    <div className="row">
                      <span>Imágenes</span>
                      <Delta actual={ultima.counts.images} previo={previa.counts.images} />
                    </div>
                    <div className="row">
                      <span>Bounding boxes</span>
                      <Delta actual={ultima.counts.annotations} previo={previa.counts.annotations} />
                    </div>
                    <div className="row">
                      <span>Categorías</span>
                      <Delta actual={ultima.counts.categories} previo={previa.counts.categories} />
                    </div>
                    <div className="row">
                      <span>Clases que cruzan {MIN_IMAGES} imágenes</span>
                      <span>{diff ? diff.crossed.length : 'Sin datos históricos'}</span>
                    </div>
                    {diff?.crossed.map((crossing) => (
                      <div className="row" key={crossing.name}>
                        <span>{crossing.name}</span>
                        <Pill kind={crossing.gained ? 'pass' : 'fail'}>
                          {crossing.previousCount} → {crossing.currentCount}
                        </Pill>
                      </div>
                    ))}
                    {diff && diff.crossed.length === 0 && (
                      <p className="state">Ninguna clase cruzó el mínimo.</p>
                    )}
                    <div className="row">
                      <span>Objetos pequeños</span>
                      {diff?.smallObjects ? (
                        <span className="mono">
                          {diff.smallObjects.before.toFixed(2)}% → {diff.smallObjects.after.toFixed(2)}%
                        </span>
                      ) : <span>Sin datos históricos</span>}
                    </div>
                    {diff?.smallObjects && (
                      <div className="row">
                        <span>Cambio en puntos porcentuales</span>
                        <span className="mono" style={{ color: diff.smallObjects.delta < 0
                          ? 'var(--pass)' : diff.smallObjects.delta > 0 ? 'var(--fail)' : 'var(--muted)' }}>
                          {diff.smallObjects.delta > 0 ? '+' : ''}{diff.smallObjects.delta.toFixed(2)} pp
                        </span>
                      </div>
                    )}
                  </Card>
                )}

                {ultima && (
                  <Card
                    title="Última versión"
                    hint="Tres huellas distintas: los datos, el reporte de calidad y el reparto. Cambiar cualquiera produce una versión nueva."
                  >
                    <div className="row">
                      <span>Calidad</span>
                      <Pill kind={ultima.quality_status === 'pass' ? 'pass' : 'fail'}>
                        {ultima.quality_status}
                      </Pill>
                    </div>
                    <div className="row">
                      <span>Publicada en</span>
                      <Remotes publicados={ultima.published_in ?? []} />
                    </div>
                    {(ultima.published_in ?? []).map((publicacion) => (
                      <div className="row" key={publicacion.remote}>
                        <span className="mono" style={{ fontSize: 11 }}>
                          {publicacion.remote}
                        </span>
                        <span className="mono" style={{ fontSize: 11, wordBreak: 'break-all' }}>
                          {publicacion.storage_uri}
                        </span>
                      </div>
                    ))}
                    {(
                      [
                        ['dataset', ultima.dataset_fingerprint],
                        ['calidad', ultima.quality_report_fingerprint],
                        ['splits', ultima.splits_fingerprint],
                      ] as const
                    ).map(([label, hash]) => (
                      <div className="row" key={label}>
                        <span>{label}</span>
                        <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
                          {hash.slice(0, 20)}…
                        </span>
                      </div>
                    ))}
                    {!(ultima.published_in ?? []).some((p) => p.remote === 'prod') && (
                      <div className="banner warn">
                        Esta versión no está en <span className="mono">prod</span>: existe solo en
                        el remote local. Promoverla es un paso aparte, y hasta que ocurra el bucket
                        de producción no la tiene.
                      </div>
                    )}
                    {ultima.quality_status === 'fail' && (
                      <div className="banner warn">
                        Esta versión se publicó con la compuerta en fail (se usó{' '}
                        <span className="mono">--force</span>). No debería promoverse a producción.
                      </div>
                    )}
                  </Card>
                )}
              </div>
            </div>
          </>
        );
      }}
    </Resolve>
  );
}
