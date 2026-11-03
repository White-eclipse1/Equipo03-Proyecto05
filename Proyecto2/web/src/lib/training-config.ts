/**
 * Config de entrenamiento en el cliente: valores por defecto y validación con
 * los mismos rangos de `Proyecto3/docs/contratos.md §3`.
 *
 * El portal valida ANTES de enviar (criterio 2.2): un valor fuera de rango se
 * avisa junto al campo y bloquea el lanzamiento, sin llegar al servidor. El
 * servidor vuelve a validar y responde 422; ese error también se muestra. Esta
 * es una segunda fuente de verdad respecto al backend a propósito acotada: si
 * el contrato cambia, hay que alinear ambos (regla 11 de AGENTS.md).
 */

import type { TrainingConfig } from './api';

/** Valores por defecto razonables; todos válidos según el contrato. */
export const DEFAULT_TRAINING_CONFIG: TrainingConfig = {
  optimizer: 'adamw',
  batch_size: 32,
  max_epochs: 30,
  learning_rate: 0.0003,
  image_size: 224,
  hidden_layers: [256],
  dropout: 0.3,
  seed: 42,
  patience: 5,
  min_delta: 0.001,
  monitor_metric: 'val_accuracy',
};

export type FieldErrors = Partial<Record<keyof TrainingConfig, string>>;

const OPTIMIZERS = ['sgd', 'adam', 'adamw'];
const MONITOR = ['val_accuracy', 'val_loss'];
const U32_MAX = 2 ** 32 - 1;

const intInRange = (value: number, min: number, max: number): boolean =>
  Number.isInteger(value) && value >= min && value <= max;

/** Devuelve los errores por campo; objeto vacío = configuración válida. */
export function validateTrainingConfig(config: TrainingConfig): FieldErrors {
  const errors: FieldErrors = {};

  if (!OPTIMIZERS.includes(config.optimizer))
    errors.optimizer = 'optimizer debe ser sgd, adam o adamw';
  if (!intInRange(config.batch_size, 1, 256))
    errors.batch_size = 'batch_size debe ser un entero entre 1 y 256';
  if (!intInRange(config.max_epochs, 1, 200))
    errors.max_epochs = 'max_epochs debe ser un entero entre 1 y 200';
  if (!(config.learning_rate > 0 && config.learning_rate <= 1))
    errors.learning_rate = 'learning_rate debe ser mayor que 0 y hasta 1';
  if (!intInRange(config.image_size, 32, 512) || config.image_size % 32 !== 0)
    errors.image_size = 'image_size debe estar entre 32 y 512 y ser múltiplo de 32';
  if (
    !Array.isArray(config.hidden_layers) ||
    config.hidden_layers.length > 4 ||
    config.hidden_layers.some((n) => !intInRange(n, 8, 4096))
  )
    errors.hidden_layers = 'hidden_layers: de 0 a 4 capas, cada una entre 8 y 4096';
  if (!(config.dropout >= 0 && config.dropout <= 0.9))
    errors.dropout = 'dropout debe estar entre 0 y 0.9';
  if (!intInRange(config.seed, 0, U32_MAX))
    errors.seed = `seed debe ser un entero entre 0 y ${U32_MAX}`;
  if (!intInRange(config.patience, 1, 50))
    errors.patience = 'patience debe ser un entero entre 1 y 50';
  if (!(config.min_delta >= 0 && config.min_delta <= 0.1))
    errors.min_delta = 'min_delta debe estar entre 0 y 0.1';
  if (!MONITOR.includes(config.monitor_metric))
    errors.monitor_metric = 'monitor_metric debe ser val_accuracy o val_loss';

  return errors;
}

export function isConfigValid(errors: FieldErrors): boolean {
  return Object.keys(errors).length === 0;
}

/**
 * Motivo por el que NO se puede lanzar un entrenamiento, o `null` si sí se puede
 * (criterio T19: bloquear si la compuerta falló o el manifiesto no está
 * congelado, mostrando el motivo).
 */
export function launchBlockReason(qualityStatus: string, hasFrozenManifest: boolean): string | null {
  if (qualityStatus !== 'pass')
    return 'El release no pasó la compuerta de calidad; no se puede entrenar sobre él.';
  if (!hasFrozenManifest)
    return 'Genera y congela el manifiesto 70/20/10 antes de lanzar un entrenamiento.';
  return null;
}

/** Parsea el texto de `hidden_layers` ("256" o "512, 128") a una lista. */
export function parseHiddenLayers(text: string): number[] {
  return text
    .split(',')
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
    .map(Number);
}
