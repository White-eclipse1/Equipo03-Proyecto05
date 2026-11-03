import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import Evaluation from '../src/pages/Evaluation';

// Criterio 6.3: la evaluación debe mostrar su procedencia — el run elegido (con
// enlace a Experiments), el manifiesto y su hash, el release y el checkpoint.

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
});

describe('Evaluation — procedencia (6.3)', () => {
  it('enlaza el run a Experiments', async () => {
    render(<Evaluation />);
    const link = await screen.findByRole('link', { name: /experiments/i });
    expect(link.getAttribute('href')).toContain('#/experiments');
  });

  it('muestra manifiesto, hash, release y checkpoint del candidato', async () => {
    render(<Evaluation />);
    // Manifiesto (id) y su hash (del selection.json).
    expect(await screen.findByText('m-0.1.3-s42-1')).toBeInTheDocument();
    expect(await screen.findByText(/b1a2c3d4e5f60718/)).toBeInTheDocument();
    // Release del que deriva el manifiesto (del manifiesto congelado).
    expect(await screen.findByText('0.1.3')).toBeInTheDocument();
    // Checkpoint: su SHA-256 (del selection.json).
    expect(await screen.findByText(/c0ffee0000000000/)).toBeInTheDocument();
  });
});
