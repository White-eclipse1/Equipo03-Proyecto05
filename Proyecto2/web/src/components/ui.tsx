/** Piezas de interfaz compartidas y el hook de carga. */

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { ApiError } from '../lib/api';

type State<T> =
  | { kind: 'loading' }
  | { kind: 'ready'; data: T }
  | { kind: 'empty'; message: string }
  | { kind: 'error'; message: string };

/**
 * Carga datos de la API distinguiendo tres finales que significan cosas
 * distintas para quien mira: cargando, "el pipeline aun no produjo esto" (503)
 * y un fallo real. Mezclarlos haria imposible dar un mensaje util.
 */
export function useApi<T>(loader: () => Promise<T>): State<T> {
  const [state, setState] = useState<State<T>>({ kind: 'loading' });

  const run = useCallback(() => {
    let cancelled = false;
    setState({ kind: 'loading' });
    loader()
      .then((data) => !cancelled && setState({ kind: 'ready', data }))
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 503) {
          setState({ kind: 'empty', message: error.message });
        } else {
          setState({
            kind: 'error',
            message: error instanceof Error ? error.message : 'Error desconocido',
          });
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(run, [run]);
  return state;
}

/** Resuelve los tres estados no felices y delega el feliz al hijo. */
export function Resolve<T>({
  state,
  children,
}: {
  state: State<T>;
  children: (data: T) => ReactNode;
}) {
  if (state.kind === 'loading') return <p className="state">Cargando…</p>;
  if (state.kind === 'empty') return <p className="state">{state.message}</p>;
  if (state.kind === 'error')
    return (
      <div className="state">
        <p>No se pudo cargar la información.</p>
        <p className="mono">{state.message}</p>
      </div>
    );
  return <>{children(state.data)}</>;
}

export function Card({
  title,
  hint,
  aside,
  children,
}: {
  title?: string;
  hint?: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card">
      {(title || aside) && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            gap: 12,
          }}
        >
          {title && <h2>{title}</h2>}
          {aside}
        </div>
      )}
      {hint && <p className="hint">{hint}</p>}
      {children}
    </section>
  );
}

export function Tile({
  value,
  label,
  tone = 'a',
}: {
  value: ReactNode;
  label: string;
  tone?: 'a' | 'b' | 'c' | 'd' | 'fail';
}) {
  return (
    <div className={`tile tile-${tone}`}>
      <div className="value">{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}

export function Pill({ kind, children }: { kind: string; children: ReactNode }) {
  return <span className={`pill ${kind}`}>{children}</span>;
}
