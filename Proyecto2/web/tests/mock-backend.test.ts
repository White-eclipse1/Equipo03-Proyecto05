import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { type ApiError, type TrainingConfig, api } from '../src/lib/api';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';

const VALID_CONFIG: TrainingConfig = {
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

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
});

describe('mock backend de P3 (solo dev/pruebas)', () => {
  it('sirve el release aprobado 0.1.3', async () => {
    const { releases } = await api.p3.releases();
    expect(releases.map((r) => r.release_id)).toContain('0.1.3');
    expect(releases.every((r) => r.quality_status === 'pass')).toBe(true);
  });

  it('rechaza una config inválida con 422 nombrando el campo', async () => {
    try {
      await api.p3.createTrainingJob({
        kind: 'train',
        manifest_id: 'm-0.1.3-s42-1',
        config: { ...VALID_CONFIG, dropout: 1.5 },
      });
      expect.unreachable('debió rechazar el dropout fuera de rango');
    } catch (error) {
      const apiError = error as ApiError;
      expect(apiError.status).toBe(422);
      expect(apiError.message).toContain('dropout');
    }
  });

  it('encola un trabajo válido y lo puede consultar por id', async () => {
    const created = await api.p3.createTrainingJob({
      kind: 'train',
      manifest_id: 'm-0.1.3-s42-1',
      config: VALID_CONFIG,
    });
    expect(created.status).toBe('queued');

    const job = await api.p3.trainingJob(created.job_id);
    expect(job.job_id).toBe(created.job_id);
    expect(['queued', 'running', 'succeeded']).toContain(job.status);
  });

  it('lista al menos 10 corridas FINISHED de MLflow', async () => {
    const { runs } = await api.p3.runs({ status: 'FINISHED' });
    expect(runs.length).toBeGreaterThanOrEqual(10);
    expect(runs[0]).toHaveProperty('best_val_accuracy');
  });
});
