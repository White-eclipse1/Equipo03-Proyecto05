import { render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import Experiments from '../src/pages/Experiments';

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
});

describe('Página Experiments — tabla de corridas', () => {
  it('lista las corridas de MLflow, una fila por corrida', async () => {
    render(<Experiments />);
    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row');
    // Encabezado + al menos 10 corridas.
    expect(rows.length).toBeGreaterThanOrEqual(11);
  });

  it('ordena por val_accuracy descendente por defecto', async () => {
    render(<Experiments />);
    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row');
    // La primera fila de datos es la de mayor val_accuracy del fixture (0.920).
    const firstDataRow = rows[1] as HTMLElement;
    expect(within(firstDataRow).getByText('0.920')).toBeInTheDocument();
  });

  it('muestra el candidato seleccionado (selection.json)', async () => {
    render(<Experiments />);
    expect(await screen.findByText(/candidato/i)).toBeInTheDocument();
  });
});
