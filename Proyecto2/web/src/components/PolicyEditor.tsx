/**
 * Editor de `quality.yaml` desde la app.
 *
 * Hasta ahora Settings solo decía que los umbrales "viven en quality.yaml": se
 * podía ver que la compuerta bloqueaba por un check y no mover el umbral sin
 * abrir una terminal. Este formulario escribe en el archivo de verdad — el
 * mismo que lee `dq gate` — conservando sus comentarios, y el cambio se nota en
 * la siguiente corrida.
 *
 * El borrador se guarda como texto y no como números: si se convirtiera en cada
 * tecla, escribir `0.15` sería imposible (`0.` se convierte en `0` y borra el
 * punto). La conversión ocurre una sola vez, al guardar, tomando el tipo de
 * cada campo de la política que vino del servidor.
 *
 * Validar aquí los rangos sería duplicar `QualityConfig`: el servidor responde
 * 422 nombrando el campo y ese mensaje es el que se enseña.
 */

import { useState } from 'react';
import {
  api,
  ApiError,
  type PolicySaved,
  type PolicyValue,
  type QualityPolicy,
} from '../lib/api';
import { Card, Pill, Resolve, useApi } from './ui';
import RefreshAction from './RefreshAction';

const CHECKS: [string, string][] = [
  ['min_images_per_class', 'Volumen mínimo por clase'],
  ['small_objects', 'Objetos pequeños'],
  ['class_imbalance', 'Desbalance de clases'],
  ['duplicates', 'Duplicados por pHash'],
  ['degenerate_boxes', 'Cajas degeneradas'],
  ['spatial_bias', 'Sesgo espacial'],
];

const ETIQUETAS: Record<string, string> = {
  min_images: 'Imágenes distintas exigidas',
  min_classes: 'Clases que deben llegar al mínimo',
  area_ratio_threshold: 'Área mínima de la caja (fracción de su imagen)',
  max_ratio: 'Fracción máxima tolerada',
  max_ratio_max_min: 'Ratio máx/mín permitido',
  phash_hamming_distance: 'Distancia de Hamming máxima (de 64 bits)',
  grid_size: 'Lado de la rejilla',
  max_cell_share: 'Concentración máxima en una celda',
  seed: 'Semilla',
  tolerance: 'Tolerancia de estratificación',
  group_near_duplicates: 'Los casi-duplicados viajan juntos',
  train: 'train',
  val: 'val',
  test: 'test',
};

/** `{a: {b: 1}}` -> `{'a.b': '1'}`. Todo se edita como texto. */
function aplanar(valor: unknown, prefijo = ''): Record<string, string> {
  if (valor !== null && typeof valor === 'object') {
    return Object.entries(valor as Record<string, unknown>).reduce<Record<string, string>>(
      (acc, [clave, hijo]) => ({ ...acc, ...aplanar(hijo, prefijo ? `${prefijo}.${clave}` : clave) }),
      {},
    );
  }
  return { [prefijo]: String(valor) };
}

/** Rehace el objeto tomando de `molde` el tipo que espera cada campo. */
function reconstruir(molde: unknown, textos: Record<string, string>, prefijo = ''): unknown {
  if (molde !== null && typeof molde === 'object') {
    return Object.fromEntries(
      Object.entries(molde as Record<string, unknown>).map(([clave, hijo]) => [
        clave,
        reconstruir(hijo, textos, prefijo ? `${prefijo}.${clave}` : clave),
      ]),
    );
  }
  const texto = textos[prefijo];
  if (texto === undefined) return molde;
  if (typeof molde === 'boolean') return texto === 'true';
  if (typeof molde === 'number') return Number(texto);
  return texto;
}

function Campo({
  ruta,
  valor,
  original,
  onChange,
}: {
  ruta: string;
  valor: string;
  original: PolicyValue;
  onChange: (valor: string) => void;
}) {
  const clave = ruta.split('.').pop() ?? ruta;
  const etiqueta = ETIQUETAS[clave] ?? clave.replace(/_/g, ' ');

  if (typeof original === 'boolean') {
    return (
      <div className="row">
        <span style={{ color: 'var(--ink-2)' }}>{etiqueta}</span>
        <input
          type="checkbox"
          aria-label={etiqueta}
          checked={valor === 'true'}
          onChange={(event) => onChange(String(event.target.checked))}
        />
      </div>
    );
  }

  if (clave === 'severity') {
    return (
      <div className="row">
        <span style={{ color: 'var(--ink-2)' }}>Severidad</span>
        <select
          className="campo"
          aria-label={`Severidad de ${ruta.split('.')[0]}`}
          value={valor}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="error">error — bloquea el release</option>
          <option value="warning">warning — solo avisa</option>
        </select>
      </div>
    );
  }

  return (
    <div className="row">
      <span style={{ color: 'var(--ink-2)' }}>{etiqueta}</span>
      <input
        className="mono campo"
        style={{ width: 110, textAlign: 'right' }}
        inputMode="decimal"
        aria-label={ruta}
        value={valor}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function Formulario({ inicial, avisos }: { inicial: QualityPolicy; avisos: string[] }) {
  const base = aplanar(inicial);
  const [textos, setTextos] = useState<Record<string, string>>(base);
  const [guardando, setGuardando] = useState(false);
  const [guardado, setGuardado] = useState<PolicySaved | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sucio = Object.keys(base).some((ruta) => base[ruta] !== textos[ruta]);
  const advertencias = guardado ? guardado.warnings : avisos;

  function editar(ruta: string, valor: string) {
    setTextos((previos) => ({ ...previos, [ruta]: valor }));
    setGuardado(null);
    setError(null);
  }

  async function guardar() {
    setGuardando(true);
    setError(null);
    try {
      const resultado = await api.savePolicy(reconstruir(inicial, textos) as QualityPolicy);
      setGuardado(resultado);
    } catch (problema) {
      setError(
        problema instanceof ApiError || problema instanceof Error
          ? problema.message
          : 'Error desconocido',
      );
    } finally {
      setGuardando(false);
    }
  }

  const campos = (prefijo: string, valores: Record<string, unknown>) =>
    Object.entries(valores).map(([clave, valor]) =>
      valor !== null && typeof valor === 'object' ? (
        <div key={clave} style={{ marginTop: 6 }}>
          <p className="hint" style={{ marginBottom: 0 }}>
            {ETIQUETAS[clave] ?? clave}
          </p>
          {campos(`${prefijo}.${clave}`, valor as Record<string, unknown>)}
        </div>
      ) : (
        <Campo
          key={clave}
          ruta={`${prefijo}.${clave}`}
          original={valor as PolicyValue}
          valor={textos[`${prefijo}.${clave}`] ?? ''}
          onChange={(nuevo) => editar(`${prefijo}.${clave}`, nuevo)}
        />
      ),
    );

  return (
    <>
      <div className="cols-2">
        {CHECKS.map(([nombre, titulo]) => (
          <Card key={nombre} title={titulo} aside={<Pill kind="muted">{nombre}</Pill>}>
            {campos(nombre, inicial[nombre as keyof QualityPolicy] as Record<string, unknown>)}
          </Card>
        ))}

        <Card
          title="Splits"
          hint="No es un check de la compuerta: son los parámetros con los que `dq split` reparte train/val/test."
          aside={<Pill kind="muted">splits</Pill>}
        >
          {campos('splits', inicial.splits as unknown as Record<string, unknown>)}
        </Card>
      </div>

      <div style={{ marginTop: 14 }}>
        <Card
          title="Guardar en quality.yaml"
          hint="Se reescriben solo las líneas que cambian: los comentarios del archivo se conservan y el diff de Git enseña exactamente qué umbral se movió."
          aside={sucio ? <Pill kind="warning">sin guardar</Pill> : <Pill kind="muted">al día</Pill>}
        >
          <button className="ghost" onClick={() => void guardar()} disabled={!sucio || guardando}>
            {guardando ? 'Guardando…' : 'Guardar política'}
          </button>

          {error && (
            <div className="banner fail">
              {/* El servidor valida contra `QualityConfig` y su mensaje nombra
                  el campo: se enseña tal cual en vez de traducirlo. */}
              {error}
            </div>
          )}

          {guardado && guardado.changed.length > 0 && (
            <>
              <div className="banner pass">
                Guardado en <span className="mono">quality.yaml</span>:{' '}
                {guardado.changed.join(', ')}
              </div>
              <p className="hint" style={{ marginBottom: 0 }}>
                La compuerta lee el archivo en cada corrida, pero{' '}
                <span className="mono">quality.json</span> sigue siendo el de la política anterior
                hasta que se vuelva a medir.
              </p>
            </>
          )}

          {guardado && guardado.changed.length === 0 && (
            <div className="banner">No había nada que cambiar: la política ya era esa.</div>
          )}

          {advertencias.map((aviso) => (
            <div className="banner warn" key={aviso}>
              {aviso}
            </div>
          ))}
        </Card>
      </div>

      {/* El umbral nuevo no cambia nada hasta que se vuelve a medir: el botón
          que lo hace va aquí mismo, no en otra pantalla. */}
      {guardado && guardado.stale_reports && (
        <div style={{ marginTop: 14 }}>
          <RefreshAction />
        </div>
      )}
    </>
  );
}

export default function PolicyEditor() {
  const politica = useApi(() => api.policy());

  return (
    <Resolve state={politica}>
      {(sobre) => <Formulario inicial={sobre.data} avisos={sobre.warnings} />}
    </Resolve>
  );
}
