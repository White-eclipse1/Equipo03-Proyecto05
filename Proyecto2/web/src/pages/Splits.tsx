/** Splits: es honesto el reparto train/val/test. */

import { Legend, StackedBar } from '../components/charts';
import { Card, Pill, Resolve, Tile, useApi } from '../components/ui';
import { api, type SplitName } from '../lib/api';

const COLOR: Record<SplitName, string> = {
  train: 'var(--c2)',
  val: 'var(--c3)',
  test: 'var(--c4)',
};

const ORDEN: SplitName[] = ['train', 'val', 'test'];

export default function Splits() {
  const state = useApi(() => api.splits());

  return (
    <Resolve state={state}>
      {(envelope) => {
        const manifest = envelope.data;
        const total = ORDEN.reduce((sum, name) => sum + (manifest.counts[name] ?? 0), 0);

        const desviaciones = ORDEN.map((name) => {
          const objetivo = manifest.ratios[name] ?? 0;
          const real = total ? (manifest.counts[name] ?? 0) / total : 0;
          return { name, real, objetivo, delta: real - objetivo };
        });

        const clases = Object.entries(manifest.per_class ?? {}).sort(
          (a, b) => b[1].total - a[1].total,
        );

        // La desviación que importa es la de ESTRATIFICACIÓN: cuánto se aleja
        // cada CLASE de su proporción global, que es contra lo que se compara
        // `splits.tolerance`. La de tamaño de partición — qué tan lejos quedó
        // train del 70% — es otra cosa, y mucho más benigna; antes esta
        // pantalla enseñaba esa y la llamaba igual.
        const peor = clases.length
          ? Math.max(...clases.map(([, c]) => c.max_deviation))
          : Math.max(...desviaciones.map((d) => Math.abs(d.delta)));

        // Fuga real, contada aquí y no asumida: un image_id en dos particiones.
        const vistos = new Set<number>();
        const repetidos = new Set<number>();
        for (const a of manifest.assignments) {
          if (vistos.has(a.image_id)) repetidos.add(a.image_id);
          vistos.add(a.image_id);
        }
        const sinFuga = repetidos.size === 0;
        const cuadranConteos = ORDEN.every(
          (name) =>
            manifest.assignments.filter((a) => a.split === name).length ===
            (manifest.counts[name] ?? 0),
        );

        return (
          <>
            <div className="page-head">
              <div>
                <h1>Splits</h1>
                <p className="page-sub">
                  Reparto en entrenamiento, validación y prueba. Estratificado por{' '}
                  <span className="mono">{manifest.stratified_by}</span>, y los casi-duplicados se
                  asignan juntos para que ninguna copia cruce de partición.
                </p>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Pill kind="muted">seed = {manifest.seed}</Pill>
                <Pill kind="accent">{total} imágenes</Pill>
              </div>
            </div>

            <div className="tiles">
              {ORDEN.map((name) => (
                <Tile
                  key={name}
                  value={(manifest.counts[name] ?? 0).toLocaleString('es')}
                  label={`${name} · objetivo ${((manifest.ratios[name] ?? 0) * 100).toFixed(0)}%`}
                  tone={name === 'train' ? 'b' : name === 'val' ? 'c' : 'd'}
                />
              ))}
              <Tile
                value={`${(peor * 100).toFixed(1)}%`}
                label="Desviación máxima por clase"
                tone={peor > 0.05 ? 'fail' : 'a'}
              />
            </div>

            <Card
              title="Reparto"
              hint="Cada segmento es proporcional al número de imágenes de esa partición."
            >
              <StackedBar
                segments={ORDEN.map((name) => ({
                  label: name,
                  value: manifest.counts[name] ?? 0,
                  color: COLOR[name],
                }))}
              />
              <Legend items={ORDEN.map((name) => ({ label: name, color: COLOR[name] }))} />
            </Card>

            {clases.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <Card
                  title="Distribución por clase"
                  hint="Estratificar significa que cada clase conserva su proporción dentro de cada partición. Δ es la peor diferencia entre la proporción de la clase en una partición y su proporción global."
                >
                  <table>
                    <thead>
                      <tr>
                        <th>Clase</th>
                        <th className="num">Total</th>
                        {ORDEN.map((name) => (
                          <th key={name} className="num">
                            {name}
                          </th>
                        ))}
                        <th className="num">Δ máx</th>
                      </tr>
                    </thead>
                    <tbody>
                      {clases.map(([nombre, c]) => (
                        <tr key={nombre}>
                          <td>{nombre}</td>
                          <td className="num mono">{c.total.toLocaleString('es')}</td>
                          {ORDEN.map((name) => (
                            <td key={name} className="num mono">
                              {c[name].toLocaleString('es')}
                              <span className="hint" style={{ marginLeft: 6 }}>
                                {c.total ? `${((c[name] / c.total) * 100).toFixed(0)}%` : '—'}
                              </span>
                            </td>
                          ))}
                          <td
                            className="num mono"
                            style={{
                              color: c.max_deviation > 0.05 ? 'var(--fail)' : 'var(--muted)',
                            }}
                          >
                            {(c.max_deviation * 100).toFixed(1)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="hint" style={{ marginTop: 12, marginBottom: 0 }}>
                    Se cuentan imágenes distintas, no cajas. Una imagen con cajas de dos clases
                    suma en las dos, así que los totales por clase pueden superar las{' '}
                    {total.toLocaleString('es')} imágenes del reparto.
                  </p>
                </Card>
              </div>
            )}

            <div className="cols-2" style={{ marginTop: 14 }}>
              <Card
                title="Proporción real contra objetivo"
                hint="Un reparto que se aleja del objetivo hace que las métricas de validación dejen de ser comparables entre corridas."
              >
                <table>
                  <thead>
                    <tr>
                      <th>Partición</th>
                      <th className="num">Imágenes</th>
                      <th className="num">Real</th>
                      <th className="num">Objetivo</th>
                      <th className="num">Δ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {desviaciones.map((d) => (
                      <tr key={d.name}>
                        <td>{d.name}</td>
                        <td className="num mono">{manifest.counts[d.name] ?? 0}</td>
                        <td className="num mono">{(d.real * 100).toFixed(1)}%</td>
                        <td className="num mono">{(d.objetivo * 100).toFixed(0)}%</td>
                        <td
                          className="num mono"
                          style={{
                            color: Math.abs(d.delta) > 0.05 ? 'var(--fail)' : 'var(--muted)',
                          }}
                        >
                          {d.delta >= 0 ? '+' : ''}
                          {(d.delta * 100).toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>

              <Card title="Integridad del reparto">
                <div className="row">
                  <div className="row-main">
                    <span className={`dot ${sinFuga ? 'pass' : 'fail'}`} />
                    {sinFuga
                      ? `Ninguna de las ${vistos.size.toLocaleString('es')} imágenes está en dos particiones`
                      : `${repetidos.size} imagen(es) aparecen en más de una partición`}
                  </div>
                </div>
                <div className="row">
                  <div className="row-main">
                    <span className={`dot ${cuadranConteos ? 'pass' : 'fail'}`} />
                    {cuadranConteos
                      ? 'Los conteos cuadran con las asignaciones'
                      : 'Los conteos no cuadran con las asignaciones'}
                  </div>
                </div>
                <div className="row">
                  <div className="row-main">
                    <span className={`dot ${peor > 0.05 ? 'fail' : 'pass'}`} />
                    Desviación máxima por clase del {(peor * 100).toFixed(1)}%
                  </div>
                </div>
                <div className="row">
                  <div className="row-main">
                    <span className="dot pass" />
                    {manifest.grouped_near_duplicates === 0
                      ? 'Sin grupos de casi-duplicados que repartir'
                      : `${manifest.grouped_near_duplicates} grupo(s) de casi-duplicados, cada uno entero en una sola partición`}
                  </div>
                </div>
                <div className="row">
                  <div className="row-main">
                    <span className="dot pass" />
                    Reproducible con seed = {manifest.seed}
                  </div>
                </div>
                <p className="hint" style={{ marginTop: 14, marginBottom: 0 }}>
                  Las dos primeras se cuentan aquí, sobre las{' '}
                  <span className="mono">assignments</span> del manifiesto. El contrato{' '}
                  <span className="mono">SplitsManifest</span> ya las rechaza al cargar, así que en
                  la práctica no deberían ponerse en rojo nunca — pero un punto verde que nadie
                  calcula no es una comprobación, es una promesa.
                </p>
              </Card>
            </div>
          </>
        );
      }}
    </Resolve>
  );
}
