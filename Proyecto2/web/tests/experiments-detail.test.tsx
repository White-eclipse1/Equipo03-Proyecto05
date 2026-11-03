import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import Experiments from '../src/pages/Experiments';

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
});

describe('Experiments — comparación y detalle de corridas', () => {
  it('compara los parámetros de 2 corridas seleccionadas', async () => {
    const user = userEvent.setup();
    render(<Experiments />);

    const checks = await screen.findAllByRole('checkbox', { name: /comparar/i });
    await user.click(checks[0] as HTMLElement);
    await user.click(checks[1] as HTMLElement);

    const compare = await screen.findByRole('table', { name: /comparaci/i });
    expect(within(compare).getByText('optimizer')).toBeInTheDocument();
    expect(within(compare).getByText('learning_rate')).toBeInTheDocument();
  });

  it('abre una corrida: enlace a MLflow con su run_id y curvas por época', async () => {
    const user = userEvent.setup();
    render(<Experiments />);

    const detailButtons = await screen.findAllByRole('button', { name: /detalle/i });
    await user.click(detailButtons[0] as HTMLElement);

    const link = await screen.findByRole('link', { name: /mlflow/i });
    // El enlace usa el experiment_id real de la corrida (1 en el fixture), no 0.
    expect(link.getAttribute('href') ?? '').toMatch(/\/experiments\/1\/runs\/run\d+/);

    expect(await screen.findByRole('img', { name: /curvas de accuracy/i })).toBeInTheDocument();
  });
});
