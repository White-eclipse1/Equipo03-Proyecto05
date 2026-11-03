/** Settings: la configuración efectiva, el estado de los artefactos y la política editable. */

import type { ReactNode } from 'react';
import PolicyEditor from '../components/PolicyEditor';
import { Card, Pill, Resolve, useApi } from '../components/ui';
import { api } from '../lib/api';

function Campo({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="row">
      <span style={{ color: 'var(--ink-2)' }}>{label}</span>
      <span className="mono">{value}</span>
    </div>
  );
}

export default function Settings() {
  const config = useApi(() => api.config());
  const status = useApi(() => api.status());

  return (
    <Resolve state={config}>
      {(cfg) => (
        <>
          <div className="page-head">
            <div>
              <h1>Settings</h1>
              <p className="page-sub">
                Dos configuraciones distintas. El entorno sale de <span className="mono">.env</span>{' '}
                y aquí solo se lee. Los umbrales de la política viven en{' '}
                <span className="mono">quality.yaml</span> y se editan abajo: lo que se guarda va al
                archivo que lee la compuerta.
              </p>
            </div>
            <Pill kind="accent">{cfg.app_env}</Pill>
          </div>

          <div className="cols-2">
            <div className="grid">
              <Card
                title="Artefactos del pipeline"
                hint="Qué ha producido el pipeline hasta ahora y qué comando genera cada cosa."
              >
                {status.kind === 'ready' ? (
                  Object.entries(status.data).map(([nombre, info]) => (
                    <div className="row" key={nombre}>
                      <div className="row-main">
                        <span className={`dot ${info.available ? 'pass' : 'skipped'}`} />
                        <div>
                          <div style={{ fontWeight: 500 }}>{nombre}</div>
                          <div className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
                            {info.produced_by}
                          </div>
                        </div>
                      </div>
                      <Pill kind={info.available ? 'pass' : 'muted'}>
                        {info.available ? 'generado' : 'pendiente'}
                      </Pill>
                    </div>
                  ))
                ) : (
                  <p className="state">Consultando…</p>
                )}
              </Card>

              <Card title="Base de datos" hint="MariaDB — metadatos y cajas.">
                <Campo label="Host" value={cfg.database.host} />
                <Campo label="Puerto" value={cfg.database.port} />
                <Campo label="Base" value={cfg.database.name} />
                <Campo label="Usuario" value={cfg.database.user} />
                <Campo label="Contraseña" value={<Pill kind="muted">no expuesta</Pill>} />
              </Card>
            </div>

            <div className="grid">
              <Card
                title="Almacenamiento de objetos"
                hint="MinIO en local, S3 en producción. Solo cambia el endpoint."
              >
                <Campo label="Endpoint" value={cfg.object_storage.endpoint_url} />
                {cfg.object_storage.buckets.map((bucket) => (
                  <Campo key={bucket} label="Bucket" value={bucket} />
                ))}
              </Card>

              <Card title="Dónde se cambia esto">
                <p style={{ margin: '0 0 10px', color: 'var(--ink-2)', fontSize: 13 }}>
                  El entorno sale de <span className="mono">.env</span>, validado por{' '}
                  <span className="mono">pydantic-settings</span> al arrancar. Si falta una
                  credencial, el proceso aborta en el primer segundo diciendo cuál. Eso no se
                  edita desde aquí: cambiar credenciales en caliente desde una pantalla web es
                  justo lo que no debe poder hacerse.
                </p>
                <p style={{ margin: 0, color: 'var(--ink-2)', fontSize: 13 }}>
                  Los umbrales de calidad viven aparte, en{' '}
                  <span className="mono">quality.yaml</span>, para que ajustar una política sea un
                  cambio de una línea que queda registrado en Git — y no una recompilación. Por eso
                  sí se editan aquí abajo.
                </p>
              </Card>
            </div>
          </div>

          {/* La política es lo único de esta pantalla que se escribe. Va debajo
              y con su propio encabezado para que no se confunda con la
              configuración del entorno, que es de solo lectura. */}
          <div className="page-head" style={{ marginTop: 22 }}>
            <div>
              <h1 style={{ fontSize: 20 }}>Política de calidad</h1>
              <p className="page-sub">
                Los umbrales y la severidad de cada check, tal como están en{' '}
                <span className="mono">quality.yaml</span>. Guardar reescribe solo las líneas que
                cambian y el cambio se aplica en la siguiente corrida de la compuerta, sin tocar
                una línea de código.
              </p>
            </div>
          </div>

          <PolicyEditor />
        </>
      )}
    </Resolve>
  );
}
