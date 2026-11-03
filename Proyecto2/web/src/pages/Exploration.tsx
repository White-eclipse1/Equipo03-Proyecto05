/** Exploración: la proyección 2D precomputada. */

import { useState } from 'react';
import { Legend, ScatterPlot, seriesColor } from '../components/charts';
import { Card, Pill, Resolve, Tile, useApi } from '../components/ui';
import { api } from '../lib/api';

// Por debajo de esto, los dos ejes conservan tan poca informacion que los
// racimos que se vean son casualidad, no estructura.
const VARIANZA_MINIMA_UTIL = 0.25;

export default function Exploration() {
  const [aislada, setAislada] = useState<string | null>(null);
  const exploration = useApi(() => api.exploration());
  const stats = useApi(() => api.stats());

  return (
    <Resolve state={exploration}>
      {(envelope) => {
        const manifest = envelope.data;

        // El manifiesto trae `category_id`; los nombres salen de la
        // descriptiva. Si falta, se etiqueta por id.
        const nombres =
          stats.kind === 'ready' ? Object.keys(stats.data.data.stats.images_per_class) : [];
        const etiqueta = (id: number | null) =>
          id === null ? null : (nombres[id - 1] ?? `clase ${id}`);

        const points = manifest.points.map((point) => ({
          x: point.x,
          y: point.y,
          category: etiqueta(point.category_id),
          imageId: point.image_id,
        }));

        // La proyeccion anterior a `file_name` no puede servir miniaturas: sin
        // el nombre del archivo el endpoint no sabe que imagen abrir. En vez de
        // ensenar un hueco roto, el hover se desactiva hasta regenerarla.
        const conMiniaturas = manifest.points.some((point) => Boolean(point.file_name));
        const categorias = [...new Set(points.map((p) => p.category).filter(Boolean))] as string[];
        categorias.sort();

        const fiable = manifest.variance_explained >= VARIANZA_MINIMA_UTIL;

        return (
          <>
            <div className="page-head">
              <div>
                <h1>Exploración</h1>
                <p className="page-sub">
                  Cada punto es una imagen. Las que se parecen caen cerca, así que los racimos
                  revelan grupos de fotos tomadas en condiciones parecidas, y los puntos sueltos,
                  imágenes atípicas.
                </p>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Pill kind="muted">{manifest.method.toUpperCase()}</Pill>
                <Pill kind="accent">{manifest.points.length} puntos</Pill>
              </div>
            </div>

            <div className="tiles">
              <Tile value={manifest.points.length} label="Imágenes proyectadas" tone="a" />
              <Tile
                value={`${(manifest.variance_explained * 100).toFixed(1)}%`}
                label="Varianza explicada"
                tone={fiable ? 'b' : 'fail'}
              />
              <Tile value={categorias.length} label="Clases" tone="c" />
              <Tile value={manifest.seed} label="Semilla" tone="d" />
            </div>

            {!fiable && (
              <div className="banner fail" style={{ marginTop: 0, marginBottom: 16 }}>
                Los dos ejes conservan solo el {(manifest.variance_explained * 100).toFixed(1)}% de
                la información original. Los racimos de abajo probablemente no significan nada.
              </div>
            )}

            <Card
              title={`Proyección ${manifest.method.toUpperCase()} en 2D`}
              hint="Pulsa una clase de la leyenda para aislarla."
            >
              <ScatterPlot
                points={points}
                categories={categorias}
                highlight={aislada}
                thumbnailUrl={conMiniaturas ? api.thumbnailUrl : undefined}
              />
              <Legend
                items={[
                  {
                    label: 'todas',
                    color: 'var(--ink-2)',
                    active: aislada === null,
                    onClick: () => setAislada(null),
                  },
                  ...categorias.map((name, index) => ({
                    label: name,
                    color: seriesColor(index),
                    active: aislada === null || aislada === name,
                    onClick: () => setAislada(aislada === name ? null : name),
                  })),
                ]}
              />
            </Card>

            <div style={{ marginTop: 14 }}>
              <Card title="Cómo leer esto">
                <p style={{ margin: '0 0 12px', color: 'var(--ink-2)' }}>
                  Cada imagen se convierte en una lista de números que la describe, y esa lista se
                  aplasta a dos coordenadas. Se calcula en el pipeline y no en el navegador porque
                  abrir y medir cientos de imágenes lleva decenas de segundos de CPU: eso es lo que
                  significa «precomputada».
                </p>
                <p style={{ margin: 0, color: 'var(--ink-2)' }}>
                  <b>Ojo con lo que NO es:</b> {manifest.method_detail} Dos bicicletas rosas caen
                  juntas y una bicicleta negra cae lejos de ellas, aunque las tres sean bicicletas.
                  Los racimos son de color y composición, no de significado.
                </p>
              </Card>
            </div>
          </>
        );
      }}
    </Resolve>
  );
}
