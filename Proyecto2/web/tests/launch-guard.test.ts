import { describe, expect, it } from 'vitest';
import { launchBlockReason } from '../src/lib/training-config';

describe('bloqueo del lanzamiento (F8 T19)', () => {
  it('bloquea si el release no pasó la compuerta de calidad', () => {
    expect(launchBlockReason('fail', true)).toBeTruthy();
  });

  it('bloquea si el manifiesto no está congelado', () => {
    expect(launchBlockReason('pass', false)).toBeTruthy();
  });

  it('permite lanzar con compuerta en pass y manifiesto congelado', () => {
    expect(launchBlockReason('pass', true)).toBeNull();
  });
});
