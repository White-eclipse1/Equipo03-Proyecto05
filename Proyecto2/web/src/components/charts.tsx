/**
 * Graficas en SVG, dibujadas a mano.
 *
 * Son cuatro formas simples y no compensa traer 200 KB de libreria para
 * dibujarlas. Todas las escalas se calculan aqui, asi que cada etiqueta
 * corresponde a un valor que la grafica alcanza de verdad.
 */

import { useState } from 'react';

const SERIES = [
  'var(--c1)',
  'var(--c2)',
  'var(--c3)',
  'var(--c4)',
  'var(--c5)',
  'var(--c6)',
  'var(--c7)',
  'var(--c8)',
];

export const seriesColor = (index: number) => SERIES[index % SERIES.length] as string;

/** Barras verticales con linea de umbral opcional. */
export function BarChart({
  data,
  threshold,
  thresholdLabel,
  height = 220,
}: {
  data: { label: string; value: number }[];
  threshold?: number;
  thresholdLabel?: string;
  height?: number;
}) {
  if (data.length === 0) return <p className="state">Sin datos.</p>;

  const width = 640;
  const pad = { top: 18, right: 18, bottom: 46, left: 48 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const max = Math.max(...data.map((d) => d.value), threshold ?? 0) * 1.12 || 1;
  const step = plotW / data.length;
  const barW = Math.min(50, step * 0.6);
  const y = (value: number) => pad.top + plotH - (value / max) * plotH;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto' }} role="img">
      {[0, max / 2, max].map((tick) => (
        <g key={tick}>
          <line
            x1={pad.left}
            x2={width - pad.right}
            y1={y(tick)}
            y2={y(tick)}
            stroke="var(--line)"
          />
          <text x={pad.left - 8} y={y(tick) + 4} textAnchor="end" fontSize="10" fill="var(--muted)">
            {Math.round(tick)}
          </text>
        </g>
      ))}

      {data.map((item, index) => {
        const below = threshold !== undefined && item.value < threshold;
        const cx = pad.left + step * index + step / 2;
        return (
          <g key={item.label}>
            <rect
              x={cx - barW / 2}
              y={y(item.value)}
              width={barW}
              height={Math.max(1, pad.top + plotH - y(item.value))}
              rx="4"
              fill={below ? 'var(--fail)' : seriesColor(index)}
              opacity={below ? 0.85 : 1}
            >
              <title>{`${item.label}: ${item.value}`}</title>
            </rect>
            <text
              x={cx}
              y={height - 26}
              textAnchor="middle"
              fontSize="10"
              fill="var(--ink-2)"
              transform={data.length > 6 ? `rotate(-26 ${cx} ${height - 26})` : undefined}
            >
              {item.label}
            </text>
          </g>
        );
      })}

      {threshold !== undefined && (
        <g>
          <line
            x1={pad.left}
            x2={width - pad.right}
            y1={y(threshold)}
            y2={y(threshold)}
            stroke="var(--fail)"
            strokeDasharray="5 4"
          />
          <text
            x={width - pad.right}
            y={y(threshold) - 5}
            textAnchor="end"
            fontSize="10"
            fill="var(--fail)"
            fontWeight="600"
          >
            {thresholdLabel ?? `min = ${threshold}`}
          </text>
        </g>
      )}
    </svg>
  );
}

/** Barra apilada horizontal: como se reparte un total entre categorias. */
export function StackedBar({
  segments,
  height = 46,
}: {
  segments: { label: string; value: number; color: string }[];
  height?: number;
}) {
  const total = segments.reduce((sum, s) => sum + s.value, 0) || 1;
  let x = 0;

  return (
    <svg viewBox={`0 0 640 ${height}`} style={{ width: '100%', height: 'auto' }} role="img">
      {segments.map((segment) => {
        const w = (segment.value / total) * 640;
        const node = (
          <g key={segment.label}>
            <rect x={x} y={0} width={Math.max(0, w - 3)} height={height} rx="6" fill={segment.color}>
              <title>{`${segment.label}: ${segment.value}`}</title>
            </rect>
            {w > 78 && (
              <>
                <text x={x + 13} y={20} fontSize="12" fontWeight="600" fill="#fff">
                  {segment.label} {((segment.value / total) * 100).toFixed(0)}%
                </text>
                <text x={x + 13} y={35} fontSize="11" fill="#fff" opacity="0.9">
                  {segment.value} imágenes
                </text>
              </>
            )}
          </g>
        );
        x += w;
        return node;
      })}
    </svg>
  );
}

/** Nube de puntos de la proyeccion 2D. */
export function ScatterPlot({
  points,
  categories,
  highlight,
  thumbnailUrl,
}: {
  points: { x: number; y: number; category: string | null; imageId?: number }[];
  categories: string[];
  highlight: string | null;
  /** Si se pasa, al posar el ratón sobre un punto se previsualiza su imagen. */
  thumbnailUrl?: (imageId: number) => string;
}) {
  const [encima, setEncima] = useState<{ x: number; y: number; imageId: number } | null>(null);

  if (points.length === 0) return <p className="state">Sin puntos que dibujar.</p>;

  const width = 640;
  const height = 340;
  const pad = 24;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const sx = (v: number) => pad + ((v - minX) / (maxX - minX || 1)) * (width - pad * 2);
  const sy = (v: number) => height - pad - ((v - minY) / (maxY - minY || 1)) * (height - pad * 2);

  // La miniatura es un cuadrado de lado THUMB colocado junto al punto, que se
  // voltea hacia dentro cerca de los bordes: si no, la vista previa se saldría
  // del gráfico justo en los racimos de las esquinas, que son los que más
  // interesa mirar.
  const THUMB = 96;
  const previa = encima
    ? {
        x: Math.min(Math.max(encima.x + 10, pad), width - THUMB - pad),
        y: Math.min(Math.max(encima.y - THUMB - 10, pad), height - THUMB - pad),
      }
    : null;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto' }} role="img">
      <rect
        x="1"
        y="1"
        width={width - 2}
        height={height - 2}
        rx="9"
        fill="var(--surface-2)"
        stroke="var(--line)"
      />
      {points.map((point, index) => {
        const dimmed = highlight !== null && point.category !== highlight;
        const cx = sx(point.x);
        const cy = sy(point.y);
        const activo = encima?.imageId === point.imageId;
        const conPrevia = thumbnailUrl !== undefined && point.imageId !== undefined && !dimmed;
        return (
          <circle
            key={index}
            cx={cx}
            cy={cy}
            r={dimmed ? 2 : activo ? 5 : 3.2}
            fill={point.category ? seriesColor(categories.indexOf(point.category)) : 'var(--c8)'}
            opacity={dimmed ? 0.12 : 0.75}
            stroke={activo ? 'var(--text)' : 'none'}
            strokeWidth={activo ? 1.5 : 0}
            style={conPrevia ? { cursor: 'crosshair' } : undefined}
            onMouseEnter={
              conPrevia
                ? () => setEncima({ x: cx, y: cy, imageId: point.imageId as number })
                : undefined
            }
            onMouseLeave={conPrevia ? () => setEncima(null) : undefined}
          >
            <title>{point.category ?? 'sin clase'}</title>
          </circle>
        );
      })}
      {previa && encima && thumbnailUrl && (
        // `pointerEvents: none` es lo que evita el parpadeo: sin él la propia
        // miniatura recibe el ratón, el círculo dispara su onMouseLeave, la
        // miniatura desaparece, el ratón vuelve al círculo, y así en bucle.
        <g style={{ pointerEvents: 'none' }}>
          <rect
            x={previa.x - 3}
            y={previa.y - 3}
            width={THUMB + 6}
            height={THUMB + 6}
            rx="6"
            fill="var(--surface)"
            stroke="var(--line)"
          />
          <image
            href={thumbnailUrl(encima.imageId)}
            x={previa.x}
            y={previa.y}
            width={THUMB}
            height={THUMB}
            preserveAspectRatio="xMidYMid slice"
          />
        </g>
      )}
      <text x={pad} y={height - 8} fontSize="10" fill="var(--muted)">
        componente principal 1 →
      </text>
    </svg>
  );
}

/** Curvas por época: una polilínea por serie, con escala Y compartida. */
export function LineChart({
  title,
  series,
  height = 200,
}: {
  title: string;
  series: { label: string; color: string; values: number[] }[];
  height?: number;
}) {
  const n = Math.max(0, ...series.map((s) => s.values.length));
  if (n === 0) return <p className="state">Sin datos.</p>;

  const width = 640;
  const pad = { top: 16, right: 16, bottom: 28, left: 42 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const all = series.flatMap((s) => s.values);
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const x = (i: number) => pad.left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v: number) => pad.top + plotH - ((v - min) / span) * plotH;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      style={{ width: '100%', height: 'auto' }}
      role="img"
      aria-label={title}
    >
      {[min, (min + max) / 2, max].map((tick) => (
        <g key={tick}>
          <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} stroke="var(--line)" />
          <text x={pad.left - 6} y={y(tick) + 4} textAnchor="end" fontSize="10" fill="var(--muted)">
            {tick.toFixed(2)}
          </text>
        </g>
      ))}
      {series.map((serie) => (
        <polyline
          key={serie.label}
          fill="none"
          stroke={serie.color}
          strokeWidth="2"
          points={serie.values.map((v, i) => `${x(i)},${y(v)}`).join(' ')}
        >
          <title>{serie.label}</title>
        </polyline>
      ))}
      <text x={pad.left} y={height - 8} fontSize="10" fill="var(--muted)">
        época →
      </text>
    </svg>
  );
}

export function Legend({
  items,
}: {
  items: { label: string; color: string; active?: boolean; onClick?: () => void }[];
}) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 12 }}>
      {items.map((item) => (
        <button
          key={item.label}
          onClick={item.onClick}
          style={{
            appearance: 'none',
            border: 0,
            background: 'none',
            font: 'inherit',
            fontSize: 11.5,
            color: 'var(--ink-2)',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            cursor: item.onClick ? 'pointer' : 'default',
            opacity: item.active === false ? 0.35 : 1,
            padding: 0,
          }}
        >
          <span className="dot" style={{ background: item.color }} />
          {item.label}
        </button>
      ))}
    </div>
  );
}
