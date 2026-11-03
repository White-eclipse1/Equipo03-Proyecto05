import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Models from '../src/pages/Models';

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Models — backend sin acceso a S3 (503, fix #17)', () => {
  it('muestra un estado "no disponible" claro en vez de un error crudo', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: 'S3 no está disponible' }, 503)),
    );
    render(<Models />);
    expect(await screen.findByText(/no disponible/i)).toBeInTheDocument();
  });
});
