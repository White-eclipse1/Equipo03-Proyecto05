/** Overview: está sano el dataset y puede publicarse. */

import { BarChart } from '../components/charts';
import RefreshAction from '../components/RefreshAction';
import { Card, Pill, Resolve, Tile, useApi } from '../components/ui';
import { api, comparison, formatMetric, type CheckResult } from '../lib/api';

function CheckRow({ check }: { check: CheckResult }) {
  return (
    <div className="row">
      <div className="row-main">
        <span className={`dot ${check.status}`} />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 500 }}>{check.name.replace(/_/g, ' ')}</div>
          <div className="mono" style={{ color: 'var(--muted)', fontSize: 11.5 }}>
            {formatMetric(check.observed, check.name)} {comparison(check.name)}{' '}
            {formatMetric(check.threshold, check.name)}
          </div>
        </div>
      </div>
      <Pill kind={check.status === 'fail' ? check.severity : check.status}>
        {check.status === 'fail' ? check.severity : check.status}
      </Pill>
    </div>
  );
}

export default function Overview() {
  const quality = useApi(() => api.quality());
  const stats = useApi(() => api.stats());

  return (
    <Resolve state={quality}>
      {(envelope) => {
        const report = envelope.data;
        const blocked = report.exit_code === 1;
        const blocking = report.checks.filter(
          (c) => c.status === 'fail' && c.severity === 'error',
        );
        const warnings = report.checks.filter(
          (c) => c.status === 'fail' && c.severity === 'warning',
        );

        const perClass =
          stats.kind === 'ready'
            ? Object.entries(stats.data.data.stats.images_per_class)
                .sort((a, b) => b[1] - a[1])
                .map(([label, value]) => ({ label, value }))
            : [];
        const minCheck = report.checks.find((c) => c.name === 'min_images_per_class');

        return (
          <>
            <div className="page-head">
              <div>
                <h1>Dataset overview</h1>
                <p className="page-sub">
                  Evaluado el {report.generated_at.slice(0, 16).replace('T', ' ')} · huella{' '}
                  <span className="mono">{report.dataset_fingerprint.slice(0, 12)}…</span>
                </p>
              </div>
              <Pill kind={blocked ? 'fail' : 'pass'}>
                {blocked ? 'Release bloqueado' : 'Release permitido'}
              </Pill>
            </div>

            <div className="tiles">
              <Tile value={report.totals.images.toLocaleString('es')} label="Imágenes" tone="a" />
              <Tile
                value={report.totals.annotations.toLocaleString('es')}
                label="Bounding boxes"
                tone="b"
              />
              <Tile value={report.totals.categories} label="Categorías" tone="c" />
              <Tile
                value={blocking.length}
                label="Checks que bloquean"
                tone={blocking.length > 0 ? 'fail' : 'd'}
              />
            </div>

            <div className="cols-2">
              <Card
                title="Imágenes por clase"
                hint={
                  minCheck
                    ? `Imágenes distintas que contienen al menos una caja de cada clase. La línea marca el mínimo exigido (${minCheck.threshold}).`
                    : 'Imágenes distintas por clase.'
                }
              >
                {perClass.length > 0 ? (
                  <BarChart
                    data={perClass}
                    threshold={minCheck?.threshold}
                    thresholdLabel={`min = ${minCheck?.threshold ?? ''}`}
                  />
                ) : (
                  <p className="state">
                    Falta la descriptiva. Corre{' '}
                    <code>dq analyze --json reports/stats.json</code>.
                  </p>
                )}
              </Card>

              <Card title="Quality gate" hint={`${warnings.length} aviso(s) que no bloquean.`}>
                {report.checks.map((check) => (
                  <CheckRow key={check.name} check={check} />
                ))}
                <div className={`banner ${blocked ? 'fail' : 'pass'}`}>
                  {blocked
                    ? `Release bloqueado — ${blocking.map((c) => c.name).join(', ')}`
                    : 'Todas las reglas bloqueantes pasan'}
                </div>
              </Card>
            </div>

            {stats.kind === 'ready' && (
              <div style={{ marginTop: 14 }}>
                {/* Media, mediana y p90 del área de caja van juntas a propósito:
                    la distribución está sesgada y una sola cifra engañaría. La
                    media por encima de la mediana es la señal de la cola larga. */}
                <Card
                  title="Contexto del dataset"
                  hint="El área de caja se lee con las tres cifras: si la media supera a la mediana, unas pocas cajas enormes arrastran el promedio y el p90 dice cuánto se estira esa cola."
                >
                  <div className="tiles" style={{ marginBottom: 0 }}>
                    <Tile
                      value={stats.data.data.stats.annotations_per_image.toFixed(2)}
                      label="Cajas por imagen"
                      tone="d"
                    />
                    <Tile
                      value={`${(stats.data.data.stats.mean_box_area_ratio * 100).toFixed(1)}%`}
                      label="Área media de una caja"
                      tone={stats.data.data.stats.mean_box_area_ratio > 0.5 ? 'c' : 'b'}
                    />
                    <Tile
                      value={`${(stats.data.data.stats.median_box_area_ratio * 100).toFixed(1)}%`}
                      label="Área mediana de una caja"
                      tone={stats.data.data.stats.median_box_area_ratio > 0.5 ? 'c' : 'b'}
                    />
                    <Tile
                      value={`${(stats.data.data.stats.p90_box_area_ratio * 100).toFixed(1)}%`}
                      label="Área de caja — p90"
                      tone="d"
                    />
                    <Tile
                      value={stats.data.data.stats.images_without_annotations}
                      label="Imágenes sin anotar"
                      tone="a"
                    />
                  </div>
                </Card>
              </div>
            )}

            {/* Lo que pinta esta pantalla sale de reportes en disco. Si alguien
                cambio el dataset, esto los vuelve a poner al dia sin terminal. */}
            <div style={{ marginTop: 14 }}>
              <RefreshAction />
            </div>
          </>
        );
      }}
    </Resolve>
  );
}
