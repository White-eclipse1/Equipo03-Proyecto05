import { describe, expect, it } from 'vitest';
import { DEFAULT_TRAINING_CONFIG, validateTrainingConfig } from '../src/lib/training-config';

describe('validación de TrainingConfig (contrato §3)', () => {
  it('acepta la configuración por defecto', () => {
    expect(validateTrainingConfig(DEFAULT_TRAINING_CONFIG)).toEqual({});
  });

  it('rechaza dropout fuera de [0, 0.9]', () => {
    expect(validateTrainingConfig({ ...DEFAULT_TRAINING_CONFIG, dropout: 1.5 }).dropout).toBeTruthy();
    expect(validateTrainingConfig({ ...DEFAULT_TRAINING_CONFIG, dropout: 0.5 }).dropout).toBeUndefined();
  });

  it('exige image_size múltiplo de 32 dentro de 32..512', () => {
    expect(validateTrainingConfig({ ...DEFAULT_TRAINING_CONFIG, image_size: 100 }).image_size).toBeTruthy();
    expect(validateTrainingConfig({ ...DEFAULT_TRAINING_CONFIG, image_size: 640 }).image_size).toBeTruthy();
    expect(validateTrainingConfig({ ...DEFAULT_TRAINING_CONFIG, image_size: 224 }).image_size).toBeUndefined();
  });

  it('limita hidden_layers a 4 capas de 8..4096', () => {
    expect(validateTrainingConfig({ ...DEFAULT_TRAINING_CONFIG, hidden_layers: [1, 2, 3, 4, 5] }).hidden_layers).toBeTruthy();
    expect(validateTrainingConfig({ ...DEFAULT_TRAINING_CONFIG, hidden_layers: [4] }).hidden_layers).toBeTruthy();
    expect(validateTrainingConfig({ ...DEFAULT_TRAINING_CONFIG, hidden_layers: [] }).hidden_layers).toBeUndefined();
  });

  it('exige learning_rate en (0, 1]', () => {
    expect(validateTrainingConfig({ ...DEFAULT_TRAINING_CONFIG, learning_rate: 0 }).learning_rate).toBeTruthy();
    expect(validateTrainingConfig({ ...DEFAULT_TRAINING_CONFIG, learning_rate: 2 }).learning_rate).toBeTruthy();
  });

  it('rechaza enteros fuera de rango (batch_size, max_epochs, patience)', () => {
    expect(validateTrainingConfig({ ...DEFAULT_TRAINING_CONFIG, batch_size: 0 }).batch_size).toBeTruthy();
    expect(validateTrainingConfig({ ...DEFAULT_TRAINING_CONFIG, max_epochs: 500 }).max_epochs).toBeTruthy();
    expect(validateTrainingConfig({ ...DEFAULT_TRAINING_CONFIG, patience: 99 }).patience).toBeTruthy();
  });
});
