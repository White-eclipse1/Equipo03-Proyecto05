import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import Training from '../src/pages/Training';

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
});

describe('Página Training — release y manifiesto', () => {
  it('lista el release aprobado 0.1.3 con su huella de dataset', async () => {
    render(<Training />);
    // La opción del release (el manifiesto `m-0.1.3-…` también contiene "0.1.3").
    expect(await screen.findByRole('option', { name: /^v0\.1\.3/ })).toBeInTheDocument();
    expect(await screen.findByText(/2200274d/)).toBeInTheDocument();
  });

  it('muestra la procedencia del release seleccionado', async () => {
    render(<Training />);
    // La huella del reporte de calidad viene de la procedencia (GET /releases/{id}).
    expect(await screen.findByText(/4d6e64aa/)).toBeInTheDocument();
  });

  it('genera el manifiesto 70/20/10 y muestra los conteos por clase', async () => {
    const user = userEvent.setup();
    render(<Training />);
    await user.click(await screen.findByRole('button', { name: /manifiesto/i }));
    expect(await screen.findByText('cat')).toBeInTheDocument();
    expect(await screen.findByText('dog')).toBeInTheDocument();
    expect(await screen.findByText('person')).toBeInTheDocument();
    // Y las tres particiones del split, como columnas de la tabla de conteos.
    // (Se consultan por rol para no colisionar con el encabezado "Training".)
    expect(await screen.findByRole('columnheader', { name: 'train' })).toBeInTheDocument();
    expect(await screen.findByRole('columnheader', { name: 'val' })).toBeInTheDocument();
    expect(await screen.findByRole('columnheader', { name: 'test' })).toBeInTheDocument();
  });
});
