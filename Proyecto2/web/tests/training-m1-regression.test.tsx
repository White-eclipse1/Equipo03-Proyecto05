import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/lib/api';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import Training from '../src/pages/Training';

// Regresión M1: con la lista REAL de releases (0.1.1 con hash de archivo nulo,
// 0.1.2 y 0.1.3), la página no debe romperse, debe elegir el primer release
// entrenable (0.1.3), deshabilitar los no entrenables con su motivo, consultar
// el manifiesto y lanzar el trabajo con experiment "p3-pruebas".

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
  vi.restoreAllMocks();
});

async function releaseSelect(): Promise<HTMLSelectElement> {
  return (await screen.findByRole('combobox', { name: /release/i })) as HTMLSelectElement;
}

describe('Training — regresión M1 (releases reales)', () => {
  it('carga sin romperse y deja seleccionado 0.1.3 (primer entrenable)', async () => {
    render(<Training />);
    expect(
      await screen.findByRole('heading', { level: 1, name: /training/i }),
    ).toBeInTheDocument();
    expect((await releaseSelect()).value).toBe('0.1.3');
  });

  it('0.1.1 y 0.1.2 quedan deshabilitados con su motivo a la vista', async () => {
    render(<Training />);
    const options = within(await releaseSelect()).getAllByRole('option') as HTMLOptionElement[];
    const byValue = Object.fromEntries(options.map((o) => [o.value, o]));

    expect(byValue['0.1.1']?.disabled).toBe(true);
    expect(byValue['0.1.2']?.disabled).toBe(true);
    expect(byValue['0.1.3']?.disabled).toBe(false);
    // El motivo EXACTO de la API aparece en el texto de cada opción.
    expect(byValue['0.1.1']?.textContent ?? '').toContain('no registra archive_sha256');
    expect(byValue['0.1.2']?.textContent ?? '').toContain('sin manifiesto congelado');
  });

  it('consulta el manifiesto y lanza el trabajo con experiment "p3-pruebas"', async () => {
    const spy = vi.spyOn(api.p3, 'createTrainingJob');
    const user = userEvent.setup();
    render(<Training />);

    await user.click(await screen.findByRole('button', { name: /manifiesto/i }));
    expect(await screen.findByText('cat')).toBeInTheDocument(); // el manifiesto se consultó

    await user.click(await screen.findByRole('button', { name: /lanzar/i }));
    await vi.waitFor(() =>
      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ experiment: 'p3-pruebas' })),
    );
  });
});
