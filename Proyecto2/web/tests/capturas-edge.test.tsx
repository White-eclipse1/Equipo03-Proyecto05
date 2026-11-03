import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CapturaEdge, CapturasRespuesta } from '../src/lib/api';
import CapturasEdge, { fechaConZona } from '../src/pages/CapturasEdge';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function captura(cambios: Partial<CapturaEdge> = {}): CapturaEdge {
  return {
    schema_version: 1,
    capture_id: 'edge01-20261015T100000-0001',
    captured_at: '2026-10-15T10:00:00-06:00',
    predicted_class: 'dog',
    confidence: 0.9312,
    device_id: 'edge01',
    model_version: '1.0.0-int8',
    model_sha256: 'ab'.repeat(32),
    image_sha256: 'cd'.repeat(32),
    image_ref: 'capturas/edge01-20261015T100000-0001.jpg',
    region: null,
    received_at: '2026-10-15T16:00:05.250+00:00',
    image_key: 'edge-capturas/fotos/edge01-20261015T100000-0001.jpg',
    image_bytes: 1234,
    image_width: 640,
    image_height: 480,
    ...cambios,
  };
}

const respuesta = (items: CapturaEdge[], errores: CapturasRespuesta['errores'] = []) =>
  jsonResponse({ items, total: items.length, errores });

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('fechaConZona', () => {
  it('conserva la zona del dispositivo y muestra UTC para Z', () => {
    expect(fechaConZona('2026-10-15T10:00:00-06:00')).toBe('2026-10-15 10:00:00 (UTC-06:00)');
    expect(fechaConZona('2026-10-15T16:00:05.250+00:00')).toBe('2026-10-15 16:00:05 (UTC)');
    expect(fechaConZona('2026-10-15T16:00:05Z')).toBe('2026-10-15 16:00:05 (UTC)');
    expect(fechaConZona('no es fecha')).toBe('no es fecha');
  });
});

describe('Capturas Edge', () => {
  it('muestra cada captura con foto y metadatos, en el orden del backend', async () => {
    const fetch = vi.fn().mockResolvedValue(
      respuesta([
        captura({ capture_id: 'edge01-b', predicted_class: 'person', confidence: 0.5 }),
        captura({ capture_id: 'edge01-a' }),
      ]),
    );
    vi.stubGlobal('fetch', fetch);
    render(<CapturasEdge />);

    const tarjetas = await screen.findAllByRole('article');
    expect(tarjetas.map((t) => t.getAttribute('aria-label'))).toEqual([
      'Captura edge01-b',
      'Captura edge01-a',
    ]);
    const segunda = within(tarjetas[1]);
    expect(segunda.getByText('dog')).toBeInTheDocument();
    expect(segunda.getByText('93.1 %')).toHaveAttribute('title', '0.9312');
    expect(segunda.getByText('2026-10-15 10:00:00 (UTC-06:00)')).toBeInTheDocument();
    expect(segunda.getByText('2026-10-15 16:00:05 (UTC)')).toBeInTheDocument();
    expect(segunda.getByText('edge01')).toBeInTheDocument();
    expect(segunda.getByText('1.0.0-int8')).toBeInTheDocument();
    expect(segunda.getByRole('img')).toHaveAttribute('src', '/api/p4/capturas/edge01-a/foto');
    expect(screen.getByText('2 captura(s)')).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith('/api/p4/capturas?limite=200', undefined);
  });

  it('dibuja el recorte en porcentajes de la foto', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        respuesta([captura({ region: { x: 160, y: 120, width: 320, height: 240 } })]),
      ),
    );
    render(<CapturasEdge />);
    const region = await screen.findByTestId('region');
    expect(region.style.left).toBe('25%');
    expect(region.style.top).toBe('25%');
    expect(region.style.width).toBe('50%');
    expect(region.style.height).toBe('50%');
    expect(screen.getByText('160,120 · 320×240')).toBeInTheDocument();
  });

  it('lista vacía con un mensaje útil', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respuesta([])));
    render(<CapturasEdge />);
    expect(await screen.findByText(/Todavía no hay capturas/)).toBeInTheDocument();
  });

  it('503 del receptor se muestra como no disponible, con el motivo', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse({ error: 'almacen_no_disponible', detail: 'Sin P4_BUCKET' }, 503),
        ),
    );
    render(<CapturasEdge />);
    expect(await screen.findByText(/Capturas no disponibles: Sin P4_BUCKET/)).toBeInTheDocument();
  });

  it('registros ilegibles quedan visibles', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          respuesta([captura()], [{ llave: 'edge-capturas/eventos/roto.json', problema: 'x' }]),
        ),
    );
    render(<CapturasEdge />);
    expect(await screen.findByText(/1 registro\(s\) no se pudieron leer/)).toBeInTheDocument();
    expect(screen.getByText('edge-capturas/eventos/roto.json')).toBeInTheDocument();
  });

  it('Actualizar trae la captura nueva arriba', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(respuesta([captura({ capture_id: 'edge01-a' })]))
      .mockResolvedValueOnce(
        respuesta([captura({ capture_id: 'edge01-nueva' }), captura({ capture_id: 'edge01-a' })]),
      );
    vi.stubGlobal('fetch', fetch);
    const user = userEvent.setup();
    render(<CapturasEdge />);
    await screen.findByLabelText('Captura edge01-a');

    await user.click(screen.getByRole('button', { name: 'Actualizar' }));

    const tarjetas = await screen.findAllByRole('article');
    expect(tarjetas[0]).toHaveAttribute('aria-label', 'Captura edge01-nueva');
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('si falla una actualización conserva la última lista y avisa', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(respuesta([captura({ capture_id: 'edge01-a' })]))
      .mockResolvedValueOnce(jsonResponse({ detail: 'Error interno' }, 500));
    vi.stubGlobal('fetch', fetch);
    const user = userEvent.setup();
    render(<CapturasEdge />);
    await screen.findByLabelText('Captura edge01-a');

    await user.click(screen.getByRole('button', { name: 'Actualizar' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /No se pudo actualizar: .*Se muestra la última lista cargada/,
    );
    expect(screen.getByLabelText('Captura edge01-a')).toBeInTheDocument();
  });

  it('un 503 al actualizar también conserva la última lista y avisa', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(respuesta([captura({ capture_id: 'edge01-a' })]))
      .mockResolvedValueOnce(
        jsonResponse({ error: 'almacen_no_disponible', detail: 'S3 no respondio' }, 503),
      );
    vi.stubGlobal('fetch', fetch);
    const user = userEvent.setup();
    render(<CapturasEdge />);
    await screen.findByLabelText('Captura edge01-a');

    await user.click(screen.getByRole('button', { name: 'Actualizar' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No se pudo actualizar: S3 no respondio. Se muestra la última lista cargada.',
    );
    expect(screen.getByLabelText('Captura edge01-a')).toBeInTheDocument();
    expect(screen.queryByText(/Capturas no disponibles/)).not.toBeInTheDocument();
  });

  it('si la primera carga falla, muestra el error en lugar de la lista', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'Error interno' }, 500)));
    render(<CapturasEdge />);
    const alerta = await screen.findByRole('alert');
    expect(alerta).toHaveTextContent('No se pudieron cargar las capturas.');
    expect(alerta).toHaveTextContent('Error interno');
  });

  it('muestra Cargando mientras llega la primera respuesta', async () => {
    let responder!: (r: Response) => void;
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise<Response>((r) => (responder = r))));
    render(<CapturasEdge />);
    expect(screen.getByText('Cargando capturas…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Actualizando…' })).toBeDisabled();

    responder(respuesta([captura({ capture_id: 'edge01-a' })]));

    expect(await screen.findByLabelText('Captura edge01-a')).toBeInTheDocument();
    expect(screen.queryByText('Cargando capturas…')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Actualizar' })).toBeEnabled();
  });

  it('cada 30 s vuelve a pedir la lista; al desmarcarlo deja de hacerlo', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(respuesta([captura({ capture_id: 'edge01-a' })]))
      .mockImplementation(() =>
        Promise.resolve(
          respuesta([captura({ capture_id: 'edge01-nueva' }), captura({ capture_id: 'edge01-a' })]),
        ),
      );
    vi.stubGlobal('fetch', fetch);
    render(<CapturasEdge />);
    await screen.findByLabelText('Captura edge01-a');
    expect(fetch).toHaveBeenCalledTimes(1);

    await act(() => vi.advanceTimersByTimeAsync(30_000));

    const tarjetas = await screen.findAllByRole('article');
    expect(tarjetas[0]).toHaveAttribute('aria-label', 'Captura edge01-nueva');
    expect(fetch).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole('checkbox', { name: 'cada 30 s' }));
    await act(() => vi.advanceTimersByTimeAsync(90_000));
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('enlaces de exportación CSV y JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respuesta([])));
    render(<CapturasEdge />);
    expect(screen.getByRole('link', { name: 'CSV' })).toHaveAttribute(
      'href',
      '/api/p4/capturas/exportar?formato=csv',
    );
    expect(screen.getByRole('link', { name: 'JSON' })).toHaveAttribute(
      'href',
      '/api/p4/capturas/exportar?formato=json',
    );
  });
});
