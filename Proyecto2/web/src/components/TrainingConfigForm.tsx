/**
 * Formulario de configuración de entrenamiento (F8 T19).
 *
 * Los 7 parámetros del contrato más seed, patience, min_delta y monitor_metric.
 * Valida en cliente con `validateTrainingConfig` (rangos de `contratos.md §3`):
 * un valor fuera de rango se avisa junto al campo y deshabilita el lanzamiento,
 * sin llegar al servidor. Al lanzar, si el servidor responde 422 se muestra su
 * mensaje (que también nombra el campo); al 202 se avisa al padre con el job_id.
 */

import { useMemo, useState } from 'react';
import { type ExperimentName, api, type TrainingConfig } from '../lib/api';
import {
  DEFAULT_TRAINING_CONFIG,
  isConfigValid,
  parseHiddenLayers,
  validateTrainingConfig,
} from '../lib/training-config';

interface Props {
  manifestId: string;
  /** Si es el manifiesto del barrido; los demás solo se entrenan en `p3-pruebas` (F12). */
  sweep?: boolean;
  onLaunched: (jobId: string) => void;
}

/** Vacío cuando el número aún no se escribió (NaN), para no pintar "NaN". */
function numValue(value: number): string {
  return Number.isNaN(value) ? '' : String(value);
}

export default function TrainingConfigForm({ manifestId, sweep = true, onLaunched }: Props) {
  const [config, setConfig] = useState<TrainingConfig>(DEFAULT_TRAINING_CONFIG);
  const [hiddenText, setHiddenText] = useState(DEFAULT_TRAINING_CONFIG.hidden_layers.join(', '));
  const [experiment, setExperiment] = useState<ExperimentName>('p3-pruebas');
  // Fuera del barrido el worker rechaza `p3-clasificador` (409): no se ofrece.
  const effectiveExperiment: ExperimentName = sweep ? experiment : 'p3-pruebas';
  const [serverError, setServerError] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);

  const errors = useMemo(() => validateTrainingConfig(config), [config]);
  const valid = isConfigValid(errors);

  function setField<K extends keyof TrainingConfig>(key: K, value: TrainingConfig[K]) {
    setConfig((prev) => ({ ...prev, [key]: value }));
  }

  function setNumber(key: keyof TrainingConfig, raw: string) {
    setField(key, (raw === '' ? Number.NaN : Number(raw)) as TrainingConfig[typeof key]);
  }

  function onHiddenChange(raw: string) {
    setHiddenText(raw);
    setField('hidden_layers', parseHiddenLayers(raw));
  }

  async function launch(event: React.FormEvent) {
    event.preventDefault();
    if (!valid || launching) return;
    setLaunching(true);
    setServerError(null);
    try {
      const { job_id } = await api.p3.createTrainingJob({
        kind: 'train',
        manifest_id: manifestId,
        config,
        experiment: effectiveExperiment,
      });
      onLaunched(job_id);
    } catch (err: unknown) {
      setServerError(err instanceof Error ? err.message : 'Error desconocido');
    } finally {
      setLaunching(false);
    }
  }

  const err = (key: keyof TrainingConfig) =>
    errors[key] ? <span className="field-error">{errors[key]}</span> : null;

  return (
    <form className="form-grid" onSubmit={launch}>
      <label className="field">
        <span>experiment</span>
        <select
          className="campo"
          value={effectiveExperiment}
          onChange={(e) => setExperiment(e.target.value as ExperimentName)}
        >
          <option value="p3-pruebas">p3-pruebas</option>
          <option value="p3-clasificador" disabled={!sweep}>
            p3-clasificador
          </option>
        </select>
      </label>

      <label className="field">
        <span>optimizer</span>
        <select
          className="campo"
          value={config.optimizer}
          onChange={(e) => setField('optimizer', e.target.value as TrainingConfig['optimizer'])}
        >
          <option value="sgd">sgd</option>
          <option value="adam">adam</option>
          <option value="adamw">adamw</option>
        </select>
        {err('optimizer')}
      </label>

      <label className="field">
        <span>batch_size</span>
        <input
          className="campo"
          type="number"
          value={numValue(config.batch_size)}
          onChange={(e) => setNumber('batch_size', e.target.value)}
        />
        {err('batch_size')}
      </label>

      <label className="field">
        <span>max_epochs</span>
        <input
          className="campo"
          type="number"
          value={numValue(config.max_epochs)}
          onChange={(e) => setNumber('max_epochs', e.target.value)}
        />
        {err('max_epochs')}
      </label>

      <label className="field">
        <span>learning_rate</span>
        <input
          className="campo"
          type="number"
          step="0.0001"
          value={numValue(config.learning_rate)}
          onChange={(e) => setNumber('learning_rate', e.target.value)}
        />
        {err('learning_rate')}
      </label>

      <label className="field">
        <span>image_size</span>
        <input
          className="campo"
          type="number"
          step="32"
          value={numValue(config.image_size)}
          onChange={(e) => setNumber('image_size', e.target.value)}
        />
        {err('image_size')}
      </label>

      <label className="field">
        <span>hidden_layers</span>
        <input
          className="campo"
          type="text"
          placeholder="p. ej. 256 o 512, 128"
          value={hiddenText}
          onChange={(e) => onHiddenChange(e.target.value)}
        />
        {err('hidden_layers')}
      </label>

      <label className="field">
        <span>dropout</span>
        <input
          className="campo"
          type="number"
          step="0.05"
          value={numValue(config.dropout)}
          onChange={(e) => setNumber('dropout', e.target.value)}
        />
        {err('dropout')}
      </label>

      <label className="field">
        <span>seed</span>
        <input
          className="campo"
          type="number"
          value={numValue(config.seed)}
          onChange={(e) => setNumber('seed', e.target.value)}
        />
        {err('seed')}
      </label>

      <label className="field">
        <span>patience</span>
        <input
          className="campo"
          type="number"
          value={numValue(config.patience)}
          onChange={(e) => setNumber('patience', e.target.value)}
        />
        {err('patience')}
      </label>

      <label className="field">
        <span>min_delta</span>
        <input
          className="campo"
          type="number"
          step="0.001"
          value={numValue(config.min_delta)}
          onChange={(e) => setNumber('min_delta', e.target.value)}
        />
        {err('min_delta')}
      </label>

      <label className="field">
        <span>monitor_metric</span>
        <select
          className="campo"
          value={config.monitor_metric}
          onChange={(e) =>
            setField('monitor_metric', e.target.value as TrainingConfig['monitor_metric'])
          }
        >
          <option value="val_accuracy">val_accuracy</option>
          <option value="val_loss">val_loss</option>
        </select>
        {err('monitor_metric')}
      </label>

      <div className="form-actions">
        {serverError && <div className="banner warn">{serverError}</div>}
        <button type="submit" className="ghost" disabled={!valid || launching}>
          {launching ? 'Lanzando…' : 'Lanzar entrenamiento'}
        </button>
      </div>
    </form>
  );
}
