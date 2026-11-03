/**
 * Mock backend de P3: un stub de `fetch` que responde las rutas `/api/p3/*`
 * desde datos de ejemplo (`p3-fixtures.ts`).
 *
 * Existe SOLO para desarrollo y pruebas mientras el backend real no está (F8 se
 * conecta al backend real el lunes). Se activa de dos formas:
 *   - en dev, con `VITE_P3_MOCK=1` (ver `main.tsx`), y
 *   - en las pruebas de componente, llamando `installP3Mock()`.
 * Nunca se importa desde el build de producción.
 *
 * Valida `TrainingConfig` con los mismos rangos de `contratos.md §3` y responde
 * 422 con el formato de FastAPI (lista en `detail`, con `loc` nombrando el
 * campo), para que el portal muestre el mismo error que dará el servidor real.
 */

import type { TrainingConfig, TrainingJob } from '../api';
import {
  DEFAULT_ACTIVE_VERSION,
  MANIFEST_ID,
  evaluation,
  evaluationExamples,
  manifestMeta,
  manifestSeed7,
  modelVersions,
  releaseDetailFor,
  releaseSummaries,
  releaseSummary,
  runDetail,
  runs,
  selection,
} from './p3-fixtures';

type FetchArgs = Parameters<typeof fetch>;
type FetchInput = FetchArgs[0];
type FetchInit = FetchArgs[1];

let originalFetch: typeof fetch | null = null;

/** Un error de validación con la forma de FastAPI. */
interface ValidationError {
  type: string;
  loc: (string | number)[];
  msg: string;
  input: unknown;
}

/** PNG 1×1 transparente: miniatura de relleno del mock (solo dev). */
const PNG_1X1 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function detail(message: string, status: number): Response {
  return json({ detail: message }, status);
}

function unprocessable(errors: ValidationError[]): Response {
  return json({ detail: errors }, 422);
}

// --- validación de TrainingConfig (contrato §3) -----------------------------

function err(field: string, type: string, msg: string, input: unknown): ValidationError {
  return { type, loc: ['body', 'config', field], msg, input };
}

const OPTIMIZERS = ['sgd', 'adam', 'adamw'];
const MONITOR = ['val_accuracy', 'val_loss'];
const U32_MAX = 2 ** 32 - 1;

/** Devuelve el primer error de rango, o `null` si la config es válida. */
function validateConfig(config: Partial<TrainingConfig> | undefined): ValidationError[] {
  if (config == null || typeof config !== 'object') {
    return [{ type: 'missing', loc: ['body', 'config'], msg: 'Field required', input: config }];
  }
  const c = config as Record<string, unknown>;
  const errors: ValidationError[] = [];
  const num = (k: string) => (typeof c[k] === 'number' ? (c[k] as number) : Number.NaN);

  if (!OPTIMIZERS.includes(String(c.optimizer)))
    errors.push(err('optimizer', 'enum', `Input should be 'sgd', 'adam' or 'adamw'`, c.optimizer));
  if (!(num('batch_size') >= 1 && num('batch_size') <= 256))
    errors.push(err('batch_size', 'range', 'Input should be between 1 and 256', c.batch_size));
  if (!(num('max_epochs') >= 1 && num('max_epochs') <= 200))
    errors.push(err('max_epochs', 'range', 'Input should be between 1 and 200', c.max_epochs));
  if (!(num('learning_rate') > 0 && num('learning_rate') <= 1))
    errors.push(err('learning_rate', 'range', 'Input should be greater than 0 and less than or equal to 1', c.learning_rate));
  if (!(num('image_size') >= 32 && num('image_size') <= 512 && num('image_size') % 32 === 0))
    errors.push(err('image_size', 'range', 'Input should be between 32 and 512 and a multiple of 32', c.image_size));
  if (!Array.isArray(c.hidden_layers) || c.hidden_layers.length > 4 || (c.hidden_layers as number[]).some((n) => n < 8 || n > 4096))
    errors.push(err('hidden_layers', 'range', 'Between 0 and 4 layers, each 8 to 4096', c.hidden_layers));
  if (!(num('dropout') >= 0 && num('dropout') <= 0.9))
    errors.push(err('dropout', 'less_than_equal', 'Input should be less than or equal to 0.9', c.dropout));
  if (!(num('seed') >= 0 && num('seed') <= U32_MAX))
    errors.push(err('seed', 'range', `Input should be between 0 and ${U32_MAX}`, c.seed));
  if (!(num('patience') >= 1 && num('patience') <= 50))
    errors.push(err('patience', 'range', 'Input should be between 1 and 50', c.patience));
  if (!(num('min_delta') >= 0 && num('min_delta') <= 0.1))
    errors.push(err('min_delta', 'less_than_equal', 'Input should be less than or equal to 0.1', c.min_delta));
  if (!MONITOR.includes(String(c.monitor_metric)))
    errors.push(err('monitor_metric', 'enum', `Input should be 'val_accuracy' or 'val_loss'`, c.monitor_metric));

  return errors;
}

// --- store de trabajos en memoria -------------------------------------------
// Persiste dentro de la sesión de la página; un recargado del navegador lo
// reinicia (el mock es cliente). La persistencia real la da el backend el lunes.

const jobs = new Map<string, TrainingJob>();
let jobSeq = 0;

// Versión de modelo activa (mutable): la puede cambiar POST /models/{v}/activate.
let activeVersion: string = DEFAULT_ACTIVE_VERSION;

// Inferencias hechas (para el envío a la cola de anotación).
const inferences = new Map<string, { annotationImageId: number | null }>();
let inferenceSeq = 0;

/** Probabilidades deterministas por versión activa (suman 1). */
function probabilitiesFor(version: string): Record<string, number> {
  return version === '0.9.0'
    ? { cat: 0.7, dog: 0.2, person: 0.1 }
    : { cat: 0.15, dog: 0.7, person: 0.15 };
}

function newJobId(): string {
  jobSeq += 1;
  return `mockjob${String(jobSeq).padStart(4, '0')}${'0'.repeat(20)}`;
}

/** Avanza el estado del trabajo en cada consulta, de forma determinista. */
function advance(job: TrainingJob): TrainingJob {
  if (job.status === 'succeeded' || job.status === 'failed') return job;
  if (job.status === 'queued') {
    job.status = 'running';
    job.started_at = job.started_at ?? job.created_at;
    job.progress = 0.25;
    job.logs.push('entrenando época 1/30');
  } else if (job.progress < 1) {
    job.progress = Math.min(1, Number((job.progress + 0.25).toFixed(2)));
    job.logs.push(`progreso ${Math.round(job.progress * 100)}%`);
    if (job.progress >= 1) {
      job.status = 'succeeded';
      job.finished_at = '2026-09-28T12:00:00Z';
      job.mlflow_run_id = runs[0]?.run_id ?? null;
      job.logs.push('terminado');
    }
  }
  return job;
}

// --- enrutado ---------------------------------------------------------------

function resolveUrl(input: FetchInput): { pathname: string; search: URLSearchParams } {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
  const url = new URL(raw, 'http://localhost');
  return { pathname: url.pathname, search: url.searchParams };
}

async function route(input: FetchInput, init: FetchInit): Promise<Response> {
  const { pathname, search } = resolveUrl(input);
  const method = (init?.method ?? 'GET').toUpperCase();
  // Solo el JSON se parsea; el multipart (inferencia) llega como FormData.
  const raw = init?.body;
  const body = typeof raw === 'string' ? JSON.parse(raw) : undefined;
  const form = raw instanceof FormData ? raw : undefined;

  // Releases
  if (pathname === '/api/p3/releases' && method === 'GET') {
    return json({ releases: releaseSummaries });
  }
  const releaseMatch = pathname.match(/^\/api\/p3\/releases\/(.+)$/);
  if (releaseMatch && method === 'GET') {
    const found = releaseDetailFor(releaseMatch[1] ?? '');
    return found ? json(found) : detail(`El release ${releaseMatch[1]} no existe`, 404);
  }

  // Manifiestos
  if (pathname === '/api/p3/manifests' && method === 'POST') {
    if (body?.release_id !== releaseSummary.release_id)
      return detail(`El release ${body?.release_id} no existe`, 404);
    // Como la API real: el congelado de ese release y esa semilla, o 409.
    if (body?.seed === 7) return json(manifestSeed7, 201);
    if (body?.seed !== 42)
      return detail(`No hay manifiesto congelado para el release ${body?.release_id} con seed ${body?.seed}.`, 409);
    return json({ manifest_id: MANIFEST_ID, manifest_hash: manifestMeta.manifest_hash, counts: manifestMeta.counts }, 201);
  }
  const manifestMatch = pathname.match(/^\/api\/p3\/manifests\/(.+)$/);
  if (manifestMatch && method === 'GET') {
    return manifestMatch[1] === MANIFEST_ID ? json(manifestMeta) : detail('Manifiesto no encontrado', 404);
  }

  // Trabajos de entrenamiento
  if (pathname === '/api/p3/training/jobs' && method === 'POST') {
    if (body?.kind !== 'train') return detail('kind debe ser "train"', 422);
    if (body?.manifest_id !== MANIFEST_ID)
      return detail('El manifiesto no existe o no está congelado', 409);
    const errors = validateConfig(body?.config);
    if (errors.length > 0) return unprocessable(errors);
    const id = newJobId();
    jobs.set(id, {
      job_id: id,
      kind: 'train',
      status: 'queued',
      progress: 0,
      config: body.config,
      logs: ['encolado (train)'],
      error: null,
      worker_id: 'mock-worker',
      created_at: '2026-09-28T11:59:00Z',
      started_at: null,
      finished_at: null,
      mlflow_run_id: null,
    });
    return json({ job_id: id, status: 'queued' }, 202);
  }
  const jobMatch = pathname.match(/^\/api\/p3\/training\/jobs\/(.+)$/);
  if (jobMatch && method === 'GET') {
    const job = jobs.get(jobMatch[1] ?? '');
    return job ? json(advance(job)) : detail('El trabajo no existe', 404);
  }

  // Corridas de MLflow
  if (pathname === '/api/p3/runs' && method === 'GET') {
    let result = [...runs];
    const manifestId = search.get('manifest_id');
    const status = search.get('status');
    if (manifestId) result = result.filter((r) => r.manifest_id === manifestId);
    if (status) result = result.filter((r) => r.status === status);
    const orderBy = search.get('order_by');
    if (orderBy === 'val_accuracy') {
      const desc = search.get('desc') !== 'false';
      result.sort((a, b) => (desc ? b.best_val_accuracy - a.best_val_accuracy : a.best_val_accuracy - b.best_val_accuracy));
    }
    return json({ runs: result });
  }
  const runMatch = pathname.match(/^\/api\/p3\/runs\/(.+)$/);
  if (runMatch && method === 'GET') {
    const run = runs.find((r) => r.run_id === runMatch[1]);
    return run ? json(runDetail(run)) : detail('El run no existe', 404);
  }

  // Candidato seleccionado (lectura). Adición propuesta a coordinar con F5.
  if (pathname === '/api/p3/selection' && method === 'GET') {
    return json(selection);
  }

  // Evaluación en test (F6). El mock simula el estado "ya evaluado".
  if (pathname === '/api/p3/evaluation' && method === 'GET') {
    return json(evaluation);
  }
  if (pathname === '/api/p3/evaluation/examples' && method === 'GET') {
    return json(evaluationExamples);
  }
  const cropMatch = pathname.match(/^\/api\/p3\/evaluation\/crops\/(.+)$/);
  if (cropMatch && method === 'GET') {
    const cropId = decodeURIComponent(cropMatch[1] ?? '');
    const known = [...evaluationExamples.correct, ...evaluationExamples.errors].some(
      (e) => e.crop_id === cropId,
    );
    if (!known) return detail(`El recorte ${cropId} no está disponible.`, 404);
    const bytes = Uint8Array.from(atob(PNG_1X1), (c) => c.charCodeAt(0));
    return new Response(bytes, { status: 200, headers: { 'Content-Type': 'image/png' } });
  }
  if (pathname === '/api/p3/evaluation/predictions' && method === 'GET') {
    const csv = 'crop_id,clase_real,clase_predicha,prob_cat,prob_dog,prob_person\n0.1.3:a4,cat,cat,0.97,0.02,0.01\n';
    return new Response(csv, {
      status: 200,
      headers: { 'Content-Type': 'text/csv; charset=utf-8' },
    });
  }

  // Versiones de modelo (F7).
  if (pathname === '/api/p3/models' && method === 'GET') {
    return json({ active_version: activeVersion, models: modelVersions });
  }
  const cardMatch = pathname.match(/^\/api\/p3\/models\/(.+)\/card$/);
  if (cardMatch && method === 'GET') {
    const entry = modelVersions.find((m) => m.version === cardMatch[1]);
    return entry
      ? new Response(`# Tarjeta ${entry.version}\n\nClasificador de imágenes (mock).\n`, {
          status: 200,
          headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
        })
      : detail(`La version ${cardMatch[1]} no esta publicada`, 404);
  }
  // Descarga de pesos, como `GET /api/p3/models/{version}/download` (contrato C2).
  const weightsMatch = pathname.match(/^\/api\/p3\/models\/(.+)\/download$/);
  if (weightsMatch && method === 'GET') {
    const entry = modelVersions.find((m) => m.version === weightsMatch[1]);
    if (!entry) return detail(`La version ${weightsMatch[1]} no esta publicada`, 404);
    if (!entry.s3.exists)
      return detail(`s3://.../${entry.version}/model.pt no existe: no hay pesos que descargar`, 409);
    const bytes = new TextEncoder().encode(`mock model.pt ${entry.version}`);
    return new Response(bytes, {
      status: 200,
      headers: {
        'Content-Type': 'application/octet-stream',
        'Content-Disposition': `attachment; filename="clasificador-${entry.version}-model.pt"`,
        'X-Model-SHA256': entry.s3.sha256,
      },
    });
  }
  const activateMatch = pathname.match(/^\/api\/p3\/models\/(.+)\/activate$/);
  if (activateMatch && method === 'POST') {
    const entry = modelVersions.find((m) => m.version === activateMatch[1]);
    if (!entry) return detail(`La version ${activateMatch[1]} no esta publicada`, 404);
    if (!entry.s3.exists)
      return detail(`s3://.../${entry.version}/model.pt no existe: no se activa`, 409);
    activeVersion = entry.version;
    return json({ active_version: activeVersion });
  }

  // Inferencia (F4/F9).
  if (pathname === '/api/p3/inference' && method === 'POST') {
    const file = form?.get('file');
    if (!(file instanceof Blob)) return detail('Falta el archivo.', 422);
    const type = file.type;
    if (type !== 'image/png' && type !== 'image/jpeg')
      return detail(`Tipo ${type || 'desconocido'} no admitido; usa JPEG o PNG.`, 415);
    if (file.size > 10 * 1024 * 1024) return detail('El archivo pasa de 10 MB.', 413);
    const bboxRaw = form?.get('bbox_xywh');
    if (typeof bboxRaw === 'string') {
      try {
        const parsed = JSON.parse(bboxRaw);
        if (!Array.isArray(parsed) || parsed.length !== 4)
          return detail('bbox_xywh debe tener 4 numeros.', 422);
      } catch {
        return detail('bbox_xywh debe ser JSON.', 422);
      }
    }
    inferenceSeq += 1;
    const id = `inf${String(inferenceSeq).padStart(4, '0')}`;
    inferences.set(id, { annotationImageId: null });
    const probs = probabilitiesFor(activeVersion);
    const predicted = Object.entries(probs).sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'dog';
    const model = modelVersions.find((m) => m.version === activeVersion);
    return json({
      inference_id: id,
      model_version: activeVersion,
      predicted_class: predicted,
      probabilities: probs,
      model_sha256: model?.s3.sha256 ?? '',
    });
  }
  const sendMatch = pathname.match(/^\/api\/p3\/inference\/(.+)\/send-to-annotation$/);
  if (sendMatch && method === 'POST') {
    const record = inferences.get(sendMatch[1] ?? '');
    if (!record) return detail('La inferencia no existe', 404);
    const first = record.annotationImageId === null;
    record.annotationImageId = 77;
    return json({ annotation_queue_item: { image_id: 77, status: 'pending' } }, first ? 201 : 200);
  }

  return detail(`Ruta mock no implementada: ${method} ${pathname}`, 404);
}

/** Reemplaza `fetch` global: intercepta `/api/p3/*` y delega el resto. */
export function installP3Mock(): void {
  if (originalFetch) return; // ya instalado
  originalFetch = globalThis.fetch;
  const base = originalFetch;
  globalThis.fetch = ((input: FetchInput, init?: FetchInit) => {
    const { pathname } = resolveUrl(input);
    if (pathname.startsWith('/api/p3/')) return route(input, init);
    return base(input as FetchArgs[0], init);
  }) as typeof fetch;
}

/** Restaura el `fetch` original y limpia el store. */
export function uninstallP3Mock(): void {
  if (originalFetch) {
    globalThis.fetch = originalFetch;
    originalFetch = null;
  }
  jobs.clear();
  jobSeq = 0;
  activeVersion = DEFAULT_ACTIVE_VERSION;
  inferences.clear();
  inferenceSeq = 0;
}

export function isP3MockActive(): boolean {
  return originalFetch != null;
}
