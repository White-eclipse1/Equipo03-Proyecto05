import { afterEach, describe, expect, it, vi } from 'vitest';
import { type ApiError, api } from '../src/lib/api';

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

describe('cliente API de P3', () => {
  it('pide solo los releases aprobados', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ releases: [{ release_id: '0.1.3', quality_status: 'pass' }] }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const res = await api.p3.releases();

    expect(fetchMock).toHaveBeenCalledWith('/api/p3/releases?approved=true', undefined);
    expect(res.releases[0]?.release_id).toBe('0.1.3');
  });

  it('lee la procedencia de un release por id', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ release_id: '0.1.3', archive_sha256: 'abc' }));
    vi.stubGlobal('fetch', fetchMock);

    await api.p3.release('0.1.3');

    expect(fetchMock).toHaveBeenCalledWith('/api/p3/releases/0.1.3', undefined);
  });

  it('aplana el 422 del servidor nombrando el campo', async () => {
    const detail = [
      {
        type: 'less_than_equal',
        loc: ['body', 'config', 'dropout'],
        msg: 'Input should be less than or equal to 0.9',
        input: 1.5,
      },
    ];
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail }, 422)));

    try {
      await api.p3.createTrainingJob({
        kind: 'train',
        manifest_id: 'm-0.1.3-s42-1',
        // biome-ignore lint: config inválida a propósito para provocar el 422
        config: {} as never,
      });
      expect.unreachable('debió lanzar ApiError');
    } catch (error) {
      const apiError = error as ApiError;
      expect(apiError.status).toBe(422);
      expect(apiError.message).toContain('config.dropout');
    }
  });
});
