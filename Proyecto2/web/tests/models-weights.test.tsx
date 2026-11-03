import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import Models from '../src/pages/Models';

// Criterio 6.4: cada versión ofrece «Descargar pesos» con su SHA-256 a la vista.

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
});

describe('Models — descargar pesos (6.4)', () => {
  it('ofrece descargar los pesos de 1.0.0 con su SHA-256 visible', async () => {
    render(<Models />);
    // La fila de 1.0.0 ya cargó.
    expect(await screen.findByText('1.0.0')).toBeInTheDocument();

    const links = await screen.findAllByRole('link', { name: /descargar pesos/i });
    const href = (l: HTMLElement) => l.getAttribute('href') ?? '';
    // C2 (#28): la descarga es /download, con el SHA-256 verificado por el backend.
    expect(links.some((l) => href(l).includes('/api/p3/models/1.0.0/download'))).toBe(true);

    // Su SHA-256 (fixture: "10" + ceros) está a la vista.
    expect(await screen.findByText(/100000000000/)).toBeInTheDocument();
  });

  it('no ofrece descarga para una versión cuyo objeto no existe en S3', async () => {
    render(<Models />);
    await screen.findByText('0.8.0'); // versión con s3.exists=false
    const links = await screen.findAllByRole('link', { name: /descargar pesos/i });
    // Solo las dos versiones presentes (1.0.0 y 0.9.0) ofrecen descarga.
    expect(links).toHaveLength(2);
    expect(links.every((l) => !(l.getAttribute('href') ?? '').includes('0.8.0'))).toBe(true);
  });
});
