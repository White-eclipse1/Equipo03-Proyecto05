import { render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import Evaluation from '../src/pages/Evaluation';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  uninstallP3Mock();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Página Evaluation', () => {
  it('se bloquea y NO revela métricas de test si no hay selección (409)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ detail: 'La selección del modelo no está cerrada' }, 409),
      ),
    );
    render(<Evaluation />);

    expect(await screen.findByText(/selección/i)).toBeInTheDocument();
    // No aparece la matriz de confusión ni la tabla de métricas.
    expect(screen.queryByRole('table', { name: /confusión/i })).not.toBeInTheDocument();
  });

  it('muestra accuracy, matriz de confusión, por clase y baseline cuando hay evaluación', async () => {
    installP3Mock();
    render(<Evaluation />);

    // Accuracy global visible.
    expect(await screen.findByText(/accuracy/i)).toBeInTheDocument();

    // Matriz de confusión con las 3 clases.
    const matrix = await screen.findByRole('table', { name: /confusión/i });
    expect(within(matrix).getAllByText('cat').length).toBeGreaterThan(0);
    expect(within(matrix).getAllByText('person').length).toBeGreaterThan(0);

    // Baseline de la clase mayoritaria.
    expect(await screen.findByText(/baseline/i)).toBeInTheDocument();
  });
});
