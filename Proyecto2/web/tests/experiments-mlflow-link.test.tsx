import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/lib/api';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import Experiments from '../src/pages/Experiments';

// Extra: el enlace a MLflow no debe depender del puerto 5000 fijo — lo toma de
// /api/config (que el despliegue fija por entorno) en tiempo de ejecución.

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
  vi.restoreAllMocks();
});

describe('Experiments — enlace a MLflow (extra)', () => {
  it('usa la URL de MLflow de /api/config, no el puerto 5000', async () => {
    vi.spyOn(api, 'config').mockResolvedValue({
      app_env: 'test',
      database: { host: 'db', port: 3306, name: 'n', user: 'u' },
      object_storage: { endpoint_url: '', buckets: [] },
      mlflow_url: 'https://mlflow.ejemplo.test',
    });
    const user = userEvent.setup();
    render(<Experiments />);

    const detalles = await screen.findAllByRole('button', { name: /detalle/i });
    await user.click(detalles[0]!);

    await vi.waitFor(() => {
      const link = screen.getByRole('link', { name: /mlflow/i });
      expect(link.getAttribute('href') ?? '').toContain('https://mlflow.ejemplo.test');
      expect(link.getAttribute('href') ?? '').not.toContain('5000');
    });
  });
});
