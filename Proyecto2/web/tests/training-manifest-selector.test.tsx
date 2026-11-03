import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/lib/api';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import Training from '../src/pages/Training';

// F12 (1.1): el release 0.1.3 tiene dos manifiestos congelados (seed 42, el del
// barrido, y seed 7). Training los lista, genera el elegido con SU semilla (no
// una fija) y los conteos cambian al cambiar de manifiesto.

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
  vi.restoreAllMocks();
});

async function manifestSelect(): Promise<HTMLSelectElement> {
  return (await screen.findByRole('combobox', { name: /manifiesto/i })) as HTMLSelectElement;
}

describe('Training — selector de manifiesto por release', () => {
  it('lista los dos manifiestos de 0.1.3, con el del barrido elegido por defecto', async () => {
    render(<Training />);
    const select = await manifestSelect();
    const values = within(select)
      .getAllByRole('option')
      .map((o) => (o as HTMLOptionElement).value);
    expect(values).toEqual(['m-0.1.3-s42-1', 'm-0.1.3-s7-1']);
    expect(select.value).toBe('m-0.1.3-s42-1');
    // El que no es del barrido avisa que se entrena en p3-pruebas.
    expect(within(select).getByRole('option', { name: /s7-1.*p3-pruebas/i })).toBeInTheDocument();
  });

  it('genera el manifiesto elegido con su semilla y los conteos cambian', async () => {
    const spy = vi.spyOn(api.p3, 'createManifest');
    const user = userEvent.setup();
    render(<Training />);
    const generar = await screen.findByRole('button', { name: /manifiesto/i });

    await user.click(generar);
    expect(await screen.findByText('m-0.1.3-s42-1')).toBeInTheDocument();
    expect(spy).toHaveBeenLastCalledWith('0.1.3', 42);
    const trainCat42 = screen.getByRole('cell', { name: '7' });
    expect(trainCat42).toBeInTheDocument();

    await user.selectOptions(await manifestSelect(), 'm-0.1.3-s7-1');
    await user.click(generar);
    expect(await screen.findByText('m-0.1.3-s7-1')).toBeInTheDocument();
    expect(spy).toHaveBeenLastCalledWith('0.1.3', 7);
    // Conteos reales del manifiesto de seed 7: 275 dog en train.
    expect(screen.getByRole('cell', { name: '275' })).toBeInTheDocument();
  });

  it('con un manifiesto que no es del barrido, el experimento queda fijo en p3-pruebas', async () => {
    const user = userEvent.setup();
    render(<Training />);
    const generar = await screen.findByRole('button', { name: /manifiesto/i });
    const experimentOption = async (name: string) =>
      (await screen.findByRole('option', { name })) as HTMLOptionElement;

    // Con el del barrido se puede elegir cualquiera de los dos experimentos.
    await user.click(generar);
    expect((await experimentOption('p3-clasificador')).disabled).toBe(false);

    // Con seed 7, p3-clasificador se deshabilita (el worker respondería 409).
    await user.selectOptions(await manifestSelect(), 'm-0.1.3-s7-1');
    await user.click(generar);
    await screen.findByText('m-0.1.3-s7-1');
    expect((await experimentOption('p3-clasificador')).disabled).toBe(true);
    const experiment = (await experimentOption('p3-pruebas')).closest('select');
    expect(experiment?.value).toBe('p3-pruebas');
  });
});
