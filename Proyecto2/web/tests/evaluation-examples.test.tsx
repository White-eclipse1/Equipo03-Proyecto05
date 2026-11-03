import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import Evaluation from '../src/pages/Evaluation';

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
});

describe('Evaluation — galería y exportación', () => {
  it('ofrece exportar el CSV de predicciones', async () => {
    render(<Evaluation />);
    const link = await screen.findByRole('link', { name: /predicciones|csv|exportar/i });
    expect(link.getAttribute('href') ?? '').toMatch(/predictions/);
  });

  it('muestra ejemplos de aciertos y de errores del test', async () => {
    render(<Evaluation />);
    // Un acierto y un error del fixture (por crop_id).
    expect(await screen.findByText(/a4/)).toBeInTheDocument();
    expect(await screen.findByText(/a17/)).toBeInTheDocument();
  });
});
