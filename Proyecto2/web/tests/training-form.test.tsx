import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TrainingConfigForm from '../src/components/TrainingConfigForm';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('formulario de configuración de entrenamiento', () => {
  it('bloquea el lanzamiento y avisa cuando un valor está fuera de rango', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const user = userEvent.setup();
    render(<TrainingConfigForm manifestId="m-0.1.3-s42-1" onLaunched={() => {}} />);

    const dropout = screen.getByLabelText(/dropout/i);
    await user.clear(dropout);
    await user.type(dropout, '1.5');

    expect(await screen.findByText(/dropout debe estar/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /lanzar/i })).toBeDisabled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('muestra el 422 del servidor nombrando el campo', async () => {
    const detail = [
      {
        type: 'less_than_equal',
        loc: ['body', 'config', 'batch_size'],
        msg: 'Input should be less than or equal to 256',
        input: 9999,
      },
    ];
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail }, 422)));
    const user = userEvent.setup();
    render(<TrainingConfigForm manifestId="m-0.1.3-s42-1" onLaunched={() => {}} />);

    // Los valores por defecto son válidos en cliente: el submit llega al servidor.
    await user.click(screen.getByRole('button', { name: /lanzar/i }));

    expect(await screen.findByText(/config\.batch_size/)).toBeInTheDocument();
  });

  it('lanza el trabajo y avisa al padre con el job_id cuando todo es válido', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ job_id: 'job123', status: 'queued' }, 202)),
    );
    const onLaunched = vi.fn();
    const user = userEvent.setup();
    render(<TrainingConfigForm manifestId="m-0.1.3-s42-1" onLaunched={onLaunched} />);

    await user.click(screen.getByRole('button', { name: /lanzar/i }));

    await vi.waitFor(() => expect(onLaunched).toHaveBeenCalledWith('job123'));
  });
});
