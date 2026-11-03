/**
 * Copilot: preguntas en lenguaje natural sobre el reporte real.
 *
 * La pantalla es obligatoria en la rúbrica y se construye ahora aunque el
 * agente MCP sea del Frente 8. Lo que queda fijado aquí es el contrato de la
 * respuesta: la rúbrica exige que se VEAN las herramientas que consultó,
 * porque una cifra sin llamada detrás es una cifra inventada.
 */

import { useEffect, useRef, useState } from 'react';
import { Card, Pill } from '../components/ui';
import { ApiError, api, type CopilotAnswer, type CopilotCitation } from '../lib/api';

interface Turno {
  role: 'user' | 'bot';
  text: string;
  tools?: CopilotAnswer['tool_calls'];
  citations?: CopilotAnswer['citations'];
}

const SUGERENCIAS = [
  '¿Por qué está bloqueado el release?',
  '¿Qué clases no llegan a 300 imágenes?',
  '¿Cuántos duplicados hay y a qué clase afectan?',
  '¿Qué checks pasan pero están cerca del umbral?',
];

const HERRAMIENTAS: [string, string][] = [
  ['get_quality_report', 'El veredicto completo: cada check con su valor y su umbral.'],
  ['get_failed_checks', 'Solo las reglas que no se cumplen. Para explicar un bloqueo.'],
  ['get_class_distribution', 'Imágenes y cajas por clase.'],
  ['get_split_report', 'Reparto train/val/test y su semilla.'],
  ['list_versions', 'Historial de releases con sus huellas.'],
];

export default function Copilot() {
  const [turnos, setTurnos] = useState<Turno[]>([]);
  const [borrador, setBorrador] = useState('');
  const [ocupado, setOcupado] = useState(false);
  const finRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    finRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turnos]);

  async function enviar(pregunta: string) {
    const texto = pregunta.trim();
    if (!texto || ocupado) return;
    setBorrador('');
    setTurnos((previos) => [...previos, { role: 'user', text: texto }]);
    setOcupado(true);
    try {
      const respuesta = await api.copilot(texto);
      setTurnos((previos) => [
          ...previos,
        {
          role: 'bot',
          text: respuesta.answer,
          tools: respuesta.tool_calls,
          citations: respuesta.citations,
        },
      ]);
    } catch (error) {
      setTurnos((previos) => [
        ...previos,
        {
          role: 'bot',
          text:
            error instanceof ApiError
              ? error.message
              : 'No se pudo contactar al Dataset Copilot. Intenta de nuevo.',
        },
      ]);
    } finally {
      setOcupado(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dataset Copilot</h1>
          <p className="page-sub">
            Responde consultando el reporte real. Cada cifra que menciona viene de una llamada a
            una herramienta, y esas llamadas se muestran bajo la respuesta.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Pill kind="muted">solo lectura</Pill>
          <Pill kind="warning">Frente 8 pendiente</Pill>
        </div>
      </div>

      <div className="cols-2">
        <Card>
          <div className="chat">
            {turnos.length === 0 && (
              <p className="state">
                Pregunta lo que quieras sobre este dataset. El agente responde consultando{' '}
                <code>quality.json</code>, no su memoria.
              </p>
            )}
            {turnos.map((turno, index) => (
              <div key={index} className={`bubble ${turno.role}`}>
                {turno.text}
                {turno.tools && (
                  <div className="toolcalls" aria-label="Llamadas MCP">
                    {turno.tools.map((llamada) => (
                      <ToolCall key={llamada.id} call={llamada} />
                    ))}
                  </div>
                )}
                {turno.citations && turno.citations.length > 0 && (
                  <div className="citations">
                    {turno.citations.map((citation) => (
                      <Citation key={citation.artifact_revision} citation={citation} />
                    ))}
                  </div>
                )}
              </div>
            ))}
            {ocupado && <div className="bubble bot">consultando el reporte…</div>}
            <div ref={finRef} />
          </div>

          <div className="composer">
            <input
              value={borrador}
              onChange={(event) => setBorrador(event.target.value)}
              onKeyDown={(event) => event.key === 'Enter' && void enviar(borrador)}
              placeholder="Pregunta sobre este dataset…"
              disabled={ocupado}
            />
            <button onClick={() => void enviar(borrador)} disabled={ocupado || !borrador.trim()}>
              Enviar
            </button>
          </div>

          <div className="suggestions">
            {SUGERENCIAS.map((sugerencia) => (
              <button key={sugerencia} onClick={() => void enviar(sugerencia)} disabled={ocupado}>
                {sugerencia}
              </button>
            ))}
          </div>
        </Card>

        <div className="grid">
          <Card
            title="Herramientas previstas"
            hint="Todas de lectura. El agente no podrá publicar versiones, borrar imágenes ni cambiar umbrales."
          >
            {HERRAMIENTAS.map(([nombre, descripcion]) => (
              <div className="row" key={nombre}>
                <div className="row-main" style={{ alignItems: 'flex-start' }}>
                  <div>
                    <div className="mono" style={{ fontSize: 12 }}>
                      {nombre}
                    </div>
                    <div style={{ fontSize: 11.5, color: 'var(--muted)' }}>{descripcion}</div>
                  </div>
                </div>
              </div>
            ))}
          </Card>

          <Card title="Por qué solo lectura">
            <p style={{ margin: 0, color: 'var(--ink-2)' }}>
              Un asistente que explica por qué falló la compuerta es útil. Uno que puede
              desactivarla destruye la razón de existir del proyecto. La restricción es diseño, no
              timidez: si alguien le pide bajar un umbral, la respuesta correcta es explicar que
              eso se hace editando <span className="mono">quality.yaml</span>, donde queda
              registrado en Git.
            </p>
          </Card>
        </div>
      </div>
    </>
  );
}

function ToolCall({ call }: { call: CopilotAnswer['tool_calls'][number] }) {
  const inputs = Object.entries(call.arguments);
  return (
    <details className={`toolcall ${call.status}`}>
      <summary>
        <span className="mono">{call.name}</span>
        <span>{call.status === 'success' ? 'consultada' : call.status}</span>
        <span>{call.duration_ms} ms</span>
      </summary>
      <div className="toolcall-detail">
        <div>
          <strong>Entradas:</strong>{' '}
          {inputs.length === 0 ? 'sin argumentos' : JSON.stringify(call.arguments)}
        </div>
        {call.citation && <Citation citation={call.citation} />}
        {call.error && <div className="tool-error">{call.error}</div>}
      </div>
    </details>
  );
}

function Citation({ citation }: { citation: CopilotCitation }) {
  const revision = citation.artifact_revision.slice(0, 12);
  return (
    <div className="citation">
      <span className="mono">{citation.artifact}</span> · rev. {revision}
      {citation.generated_at && ` · ${new Date(citation.generated_at).toLocaleString()}`}
      {citation.dataset_fingerprint && ` · dataset ${citation.dataset_fingerprint.slice(0, 12)}`}
      {citation.dataset_version && ` · v${citation.dataset_version}`}
    </div>
  );
}
