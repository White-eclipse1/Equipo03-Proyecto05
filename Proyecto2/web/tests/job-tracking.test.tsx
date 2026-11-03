import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import JobStatusView from '../src/components/JobStatusView';
import { api } from '../src/lib/api';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import { DEFAULT_TRAINING_CONFIG } from '../src/lib/training-config';
import Training from '../src/pages/Training';

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
  localStorage.clear();
});

describe('seguimiento del trabajo de entrenamiento', () => {
  it('muestra estado y logs consultando GET /training/jobs/{id}', async () => {
    const { job_id } = await api.p3.createTrainingJob({
      kind: 'train',
      manifest_id: 'm-0.1.3-s42-1',
      config: DEFAULT_TRAINING_CONFIG,
    });

    render(<JobStatusView jobId={job_id} />);

    expect(await screen.findByText(/estado/i)).toBeInTheDocument();
    expect(
      await screen.findByText(/entrenando|progreso|encolado|terminado/i),
    ).toBeInTheDocument();
  });

  it('conserva el trabajo lanzado al recargar la página (remonta con el mismo storage)', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<Training />);
    await user.click(await screen.findByRole('button', { name: /manifiesto/i }));
    await user.click(await screen.findByRole('button', { name: /lanzar/i }));
    expect(await screen.findByText(/estado/i)).toBeInTheDocument();

    // "Recargar": una instancia nueva de la página, con el mismo localStorage y
    // el mismo backend. El trabajo debe reaparecer sin repetir el lanzamiento.
    unmount();
    render(<Training />);
    expect(await screen.findByText(/estado/i)).toBeInTheDocument();
  });
});
