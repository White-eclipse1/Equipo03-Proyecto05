/** Analyzers: el detalle de cada check, con su valor contra su umbral. */

import { useState } from 'react';
import { BarChart } from '../components/charts';
import DedupeAction from '../components/DedupeAction';
import { Card, Pill, Resolve, Tile, useApi } from '../components/ui';
import {
  api,
  comparison,
  formatMetric,
  type CheckResult,
  type DuplicatesDetail,
} from '../lib/api';

const POR_QUE: Record<string, string> = {
  min_images_per_class:
    'Sin volumen no hay dataset. Se cuentan imágenes distintas que contienen al menos una caja de la clase, no cajas: una foto con siete coches aporta una imagen a car, no siete.',
  small_objects:
    'Los detectores reducen la imagen varias veces antes de decidir. Un objeto que ocupa una fracción diminuta de su foto desaparece en ese proceso y no enseña nada.',
  class_imbalance:
    'Con un desbalance grande al modelo le sale rentable ignorar la clase rara y aun así acertar casi siempre: aprende a no detectarla nunca.',
  duplicates:
    'El pHash compara cómo se ve la imagen, así que detecta copias recomprimidas o reescaladas que un md5 no vería. Inflan el conteo por clase sin aportar variedad.',
  degenerate_boxes:
    'Cajas cuyas coordenadas exceden el borde de su imagen. Las de área nula no llegan aquí: la validación de la ingesta las rechaza antes.',
  spatial_bias:
    'Si los objetos caen siempre en la misma zona, el modelo aprende la posición en vez del objeto y falla cuando uno entra por la orilla.',
};

/**
 * A qué clases afectan los duplicados.
 *
 * El analizador ya calcula los pares para decidir el veredicto; antes los
 * tiraba y solo sobrevivían los ids sobrantes. Con el detalle en `quality.json`
 * esta tarjeta —y la herramienta MCP del Copilot— responden "cuántos duplicados
 * hay y a qué clase afectan" sin volver a abrir una sola imagen.
 */
function Duplicados({ detalle }: { detalle: DuplicatesDetail }) {
  const porClase = Object.entries(detalle.images_by_class);
  // El backend las devuelve ordenadas de mayor a menor, así que la primera fija
  // la escala de las barras.
  const maximo = Math.max(0, ...porClase.map(([, imagenes]) => imagenes));

  return (
    <div style={{ marginTop: 14 }}>
      <div className="cols-2">
        <Card
          title="A qué clases afectan"
          hint="Imágenes sobrantes que contienen al menos una caja de cada clase. Una copia con cajas de dos clases suma en las dos, así que el total puede superar el número de copias. Es lo que hay que restarle a cada clase para saber con cuántas imágenes distintas se queda."
        >
          {porClase.length === 0 ? (
            <p className="state">
              {detalle.images_without_class > 0
                ? `Las ${detalle.images_without_class} copias detectadas no tienen ninguna caja: no afectan a ninguna clase.`
                : 'No hay copias que afecten a ninguna clase.'}
            </p>
          ) : (
            porClase.map(([clase, imagenes]) => (
              <div className="row" key={clase}>
                <div className="row-main">
                  <div style={{ width: '100%' }}>
                    <div style={{ fontWeight: 500 }}>{clase}</div>
                    <div className="track" style={{ marginTop: 6 }}>
                      <div
                        className="fill"
                        style={{ width: `${maximo > 0 ? (imagenes / maximo) * 100 : 0}%` }}
                      />
                    </div>
                  </div>
                </div>
                <span className="mono" style={{ whiteSpace: 'nowrap', marginLeft: 12 }}>
                  {imagenes} img · {detalle.boxes_by_class[clase] ?? 0} cajas
                </span>
              </div>
            ))
          )}
          {detalle.images_without_class > 0 && porClase.length > 0 && (
            <div className="row">
              <span style={{ color: 'var(--muted)' }}>sin ninguna caja</span>
              <span className="mono">{detalle.images_without_class} img</span>
            </div>
          )}
        </Card>

        <Card
          title="Pares detectados"
          hint={`Distancia de Hamming entre pHash, umbral ≤ ${detalle.max_distance} de 64 bits. Se conserva el id menor.`}
        >
          <div className="row">
            <span>Pares</span>
            <span className="mono">{detalle.pairs.length}</span>
          </div>
          <div className="row">
            <span>Grupos de copias</span>
            <span className="mono">{detalle.groups}</span>
          </div>
          {detalle.pairs.slice(0, 12).map((par) => (
            <div className="row" key={`${par.kept}-${par.duplicate}`}>
              <span className="mono">
                #{par.kept} ↔ #{par.duplicate}
              </span>
              <span className="mono" style={{ color: 'var(--muted)' }}>
                {(par.similarity * 100).toFixed(1)}% · {par.distance} bits
              </span>
            </div>
          ))}
          {detalle.pairs.length > 12 && (
            <p className="hint" style={{ marginBottom: 0 }}>
              y {detalle.pairs.length - 12} par(es) más.
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}

function Detalle({ check }: { check: CheckResult }) {
  const tone = check.status === 'fail' ? (check.severity === 'error' ? 'fail' : 'c') : 'b';
  return (
    <>
      <div className="tiles">
        <Tile value={formatMetric(check.observed, check.name)} label="Observado" tone={tone} />
        <Tile value={formatMetric(check.threshold, check.name)} label="Umbral" tone="d" />
        <Tile
          value={check.status === 'fail' ? check.severity : check.status}
          label={check.status === 'fail' ? 'Severidad' : 'Estado'}
          tone={tone}
        />
        <Tile value={check.offenders.length} label="Infractores" tone="a" />
      </div>

      <div className="cols-2">
        <Card title="Qué midió">
          <p style={{ margin: '0 0 12px', color: 'var(--ink-2)' }}>{check.message}</p>
          <div className="row">
            <span>Regla</span>
            <span className="mono">
              {formatMetric(check.observed, check.name)} {comparison(check.name)}{' '}
              {formatMetric(check.threshold, check.name)}
            </span>
          </div>
          <div className="row">
            <span>Si falla</span>
            <span>{check.severity === 'error' ? 'bloquea la publicación' : 'solo avisa'}</span>
          </div>
        </Card>

        <Card title="Por qué importa">
          <p style={{ margin: 0, color: 'var(--ink-2)' }}>
            {POR_QUE[check.name] ?? 'Sin descripción.'}
          </p>
        </Card>
      </div>

      {check.duplicates && <Duplicados detalle={check.duplicates} />}

      {/* La accion vive junto al analizador que la justifica, no en un menu
          aparte: quien mira los 39 duplicados es quien decide eliminarlos. */}
      {check.name === 'duplicates' && (
        <div style={{ marginTop: 14 }}>
          <DedupeAction />
        </div>
      )}

      {check.offenders.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <Card
            title="Infractores"
            hint={`${check.offenders.length} identificadores. Los primeros 60:`}
          >
            <div className="mono" style={{ color: 'var(--ink-2)', wordBreak: 'break-all' }}>
              {check.offenders.slice(0, 60).join(', ')}
              {check.offenders.length > 60 && ' …'}
            </div>
          </Card>
        </div>
      )}
    </>
  );
}

export default function Analyzers() {
  const [activo, setActivo] = useState<string | null>(null);
  const quality = useApi(() => api.quality());

  return (
    <Resolve state={quality}>
      {(envelope) => {
        const checks = envelope.data.checks;
        const actual = checks.find((c) => c.name === activo) ?? checks[0];

        // Cada check contra su propio umbral, normalizado a 100% = el umbral.
        // Es la unica forma de ponerlos en la misma grafica: sus unidades no
        // son comparables entre si (imagenes, proporciones, veces).
        const resumen = checks
          .filter((c) => c.status !== 'skipped' && c.threshold > 0)
          .map((c) => ({
            label: c.name.replace(/_/g, ' ').slice(0, 13),
            value: Math.round((c.observed / c.threshold) * 100),
          }));

        return (
          <>
            <div className="page-head">
              <div>
                <h1>Analyzers</h1>
                <p className="page-sub">
                  Seis ángulos sobre el mismo dataset. Los analizadores solo miden: la decisión de
                  bloquear es de la compuerta.
                </p>
              </div>
            </div>

            <div className="tabs">
              {checks.map((check) => (
                <button
                  key={check.name}
                  aria-pressed={actual?.name === check.name}
                  onClick={() => setActivo(check.name)}
                >
                  {check.name.replace(/_/g, ' ')}
                  <Pill kind={check.status === 'fail' ? check.severity : check.status}>
                    {check.status}
                  </Pill>
                </button>
              ))}
            </div>

            {actual && <Detalle check={actual} />}

            <div style={{ marginTop: 14 }}>
              <Card
                title="Todos los checks contra su umbral"
                hint="Normalizado: 100% es justo el umbral. Por encima, la regla no se cumple. Las unidades originales no son comparables entre sí."
              >
                <BarChart data={resumen} threshold={100} thresholdLabel="umbral = 100%" />
              </Card>
            </div>
          </>
        );
      }}
    </Resolve>
  );
}
