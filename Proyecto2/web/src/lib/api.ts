/**
 * Cliente de la API.
 *
 * Los tipos espejan los contratos congelados del Frente 2 (`quality.json`,
 * `splits.json`, `versions.json`) mas el de exploracion. Cada artefacto llega
 * envuelto en un sobre que dice quien lo produjo.
 */

export interface Envelope<T> {
  source: 'pipeline';
  produced_by: string;
  data: T;
}

// --- quality.json -----------------------------------------------------------
export type CheckStatus = 'pass' | 'fail' | 'skipped';
export type Severity = 'error' | 'warning';

/** Un par de imágenes que el pHash considera la misma foto. */
export interface DuplicatePair {
  kept: number;
  duplicate: number;
  distance: number;
  similarity: number;
}

/**
 * Detalle del check `duplicates`: los pares y a qué clases afectan.
 *
 * `images_by_class` cuenta imágenes SOBRANTES que contienen al menos una caja
 * de esa clase, ordenadas de mayor a menor. Una copia con cajas de dos clases
 * suma en las dos, así que la suma puede superar el total de sobrantes.
 */
export interface DuplicatesDetail {
  max_distance: number;
  pairs: DuplicatePair[];
  groups: number;
  images_by_class: Record<string, number>;
  boxes_by_class: Record<string, number>;
  images_without_class: number;
}

export interface CheckResult {
  name: string;
  status: CheckStatus;
  severity: Severity;
  observed: number;
  threshold: number;
  message: string;
  offenders: number[];
  /** Solo lo lleva el check `duplicates`; `null` en todos los demás. */
  duplicates?: DuplicatesDetail | null;
}

export interface QualityReport {
  schema_version: 1;
  generated_at: string;
  dataset_fingerprint: string;
  config_version: number;
  status: 'pass' | 'fail';
  exit_code: 0 | 1;
  totals: { images: number; annotations: number; categories: number };
  checks: CheckResult[];
}

// --- splits.json ------------------------------------------------------------
export type SplitName = 'train' | 'val' | 'test';

export interface SplitsManifest {
  schema_version: 1;
  generated_at: string;
  seed: number;
  ratios: Record<SplitName, number>;
  counts: Record<SplitName, number>;
  stratified_by: string;
  assignments: { image_id: number; split: SplitName }[];
  per_class: Record<string, ClassSplitCounts>;
  grouped_near_duplicates: number;
}

/** Cómo quedó repartida una clase entre las tres particiones. */
export interface ClassSplitCounts {
  train: number;
  val: number;
  test: number;
  total: number;
  /** Peor diferencia entre la proporción de la clase en una partición y la global. */
  max_deviation: number;
}

// --- versions.json ----------------------------------------------------------
export interface DatasetVersion {
  schema_version: 1;
  version: string;
  created_at: string;
  dataset_fingerprint: string;
  quality_report_fingerprint: string;
  splits_fingerprint: string;
  storage_uri: string;
  quality_status: 'pass' | 'fail';
  counts: { images: number; annotations: number; categories: number };
  notes: string | null;
  quality_summary?: VersionQualitySummary | null;
  archive_sha256?: string | null;
  published_in: RemotePublication[];
}

export interface VersionQualitySummary {
  distinct_images_per_class: Record<string, number>;
  small_objects_ratio: number | null;
}

/** Un remote donde está publicada una versión. */
export interface RemotePublication {
  remote: string;
  storage_uri: string;
  published_at: string;
}

export interface VersionsManifest {
  schema_version: 1;
  versions: DatasetVersion[];
}

// --- exploration.json -------------------------------------------------------
export interface ExplorationManifest {
  schema_version: 1;
  generated_at: string;
  method: 'pca' | 'tsne';
  seed: number;
  dimensions: 2;
  variance_explained: number;
  method_detail: string;
  points: {
    image_id: number;
    x: number;
    y: number;
    category_id: number | null;
    file_name: string;
  }[];
}

// --- descriptiva ------------------------------------------------------------
export interface DatasetStats {
  totals: { images: number; annotations: number; categories: number };
  images_per_class: Record<string, number>;
  boxes_per_class: Record<string, number>;
  annotations_per_image: number;
  images_without_annotations: number;
  mean_box_area_ratio: number;
  median_box_area_ratio: number;
  p90_box_area_ratio: number;
}

export interface AnalysisArtifact {
  stats: DatasetStats;
  checks: CheckResult[];
}

export interface Config {
  app_env: string;
  database: { host: string; port: number; name: string; user: string };
  object_storage: { endpoint_url: string; buckets: string[] };
  /** URL de la UI de MLflow alcanzable desde el navegador (vacía si no se configuró). */
  mlflow_url?: string;
}

// --- quality.yaml -----------------------------------------------------------
/**
 * Un check de la política: `enabled`, `severity` y los umbrales propios de ese
 * analizador. El tipo se deja abierto a propósito — los umbrales cambian de un
 * check a otro y quien decide qué es válido es `QualityConfig` en el servidor,
 * que responde 422 nombrando el campo. Duplicar aquí esas reglas solo crearía
 * una segunda fuente de verdad que se desincroniza.
 */
export type PolicyValue = boolean | number | string;
export type CheckPolicy = Record<string, PolicyValue>;

export interface SplitsPolicy {
  seed: number;
  ratios: Record<SplitName, number>;
  tolerance: number;
  group_near_duplicates: boolean;
}

export interface QualityPolicy {
  version: number;
  min_images_per_class: CheckPolicy;
  small_objects: CheckPolicy;
  class_imbalance: CheckPolicy;
  duplicates: CheckPolicy;
  degenerate_boxes: CheckPolicy;
  spatial_bias: CheckPolicy;
  splits: SplitsPolicy;
}

export interface PolicyEnvelope {
  source: 'quality.yaml';
  path: string;
  data: QualityPolicy;
  warnings: string[];
}

export interface PolicySaved {
  /** Rutas que cambiaron, como `duplicates.max_ratio`. */
  changed: string[];
  data: QualityPolicy;
  warnings: string[];
  stale_reports: boolean;
  next_steps: string[];
}

export interface DedupePlan {
  remove_count: number;
  annotations_removed: number;
  total_images: number;
  kept: number;
  sample: string[];
}

export interface DedupeResult {
  removed_images: number;
  removed_annotations?: number;
  remaining_images?: number;
  quarantine_dir?: string;
  stale_reports: boolean;
  next_steps?: string[];
  undo?: string;
  message?: string;
}

export interface RefreshResult {
  status: 'pass' | 'fail';
  exit_code: 0 | 1;
  dataset_fingerprint: string;
  totals: { images: number; annotations: number; categories: number };
  blocking: string[];
  warnings: string[];
  duration_seconds: number;
  checks: { name: string; status: CheckStatus; severity: Severity }[];
  next_steps: string[];
}

export interface CopilotAnswer {
  request_id: string;
  answer: string;
  tool_calls: CopilotToolCall[];
  citations: CopilotCitation[];
}

export interface CopilotCitation {
  artifact: string;
  artifact_revision: string;
  generated_at: string | null;
  dataset_fingerprint: string | null;
  dataset_version: string | null;
}

export interface CopilotToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  status: 'success' | 'failed' | 'rejected';
  duration_ms: number;
  citation: CopilotCitation | null;
  error: string | null;
}

// ============================================================================
// Proyecto 3 — clasificador de imágenes (contratos en `Proyecto3/docs/contratos.md`)
//
// Estos tipos espejan los esquemas CONGELADOS de P3. La API vive bajo `/api/p3/`
// y la sirve la misma app de P2. Cambiar la forma de cualquiera exige avisar al
// equipo (regla 11 de AGENTS.md); mantener este archivo alineado con el contrato.
// ============================================================================

// --- releases (contrato §4) -------------------------------------------------
export interface P3ReleaseSummary {
  release_id: string;
  dataset_fingerprint: string;
  quality_status: 'pass' | 'fail';
  created_at: string;
  counts: { images: number; annotations: number; categories: number };
  /** `null` si el release no está publicado en el remote `prod`. */
  storage_uri: string | null;
  published_in: string[];
  /** Si se puede lanzar un entrenamiento sobre este release. */
  trainable: boolean;
  /** Motivo por el que NO es entrenable (p. ej. sin paquete en prod), o `null`. */
  blocked_reason: string | null;
  /** Manifiestos congelados con los que se puede entrenar, el del barrido primero. */
  manifests: P3ManifestRef[];
}

/** Un manifiesto congelado de un release (`GET /releases`, F12). */
export interface P3ManifestRef {
  manifest_id: string;
  seed: number;
  /** El del barrido de `p3-clasificador`; los demás se entrenan en `p3-pruebas`. */
  sweep: boolean;
}

/** Procedencia completa de un release aprobado (`GET /releases/{id}`). */
export interface P3ReleaseDetail extends P3ReleaseSummary {
  quality_report_fingerprint: string;
  /** `null` si el release no tiene paquete verificable publicado. */
  archive_sha256: string | null;
}

export interface P3ReleasesResponse {
  releases: P3ReleaseSummary[];
}

// --- TrainingConfig (contrato §3) -------------------------------------------
export type P3Optimizer = 'sgd' | 'adam' | 'adamw';
export type P3MonitorMetric = 'val_accuracy' | 'val_loss';

/** Config de entrenamiento. Los rangos válidos están en `contratos.md §3`. */
export interface TrainingConfig {
  optimizer: P3Optimizer;
  batch_size: number;
  max_epochs: number;
  learning_rate: number;
  image_size: number;
  hidden_layers: number[];
  dropout: number;
  seed: number;
  patience: number;
  min_delta: number;
  monitor_metric: P3MonitorMetric;
}

// --- manifiesto (contrato §2) -----------------------------------------------
/** Conteos por clase en una partición, p. ej. `{cat: 7, dog: 6, person: 6}`. */
export type ClassCounts = Record<string, number>;

export interface ManifestCounts {
  crops: Record<SplitName, ClassCounts>;
  originals: Record<SplitName, ClassCounts>;
}

export interface ManifestClass {
  class_index: number;
  category_id: number;
  category_name: string;
}

export interface ManifestExclusion {
  annotation_id: number;
  source_image_id: number;
  reason: string;
}

export interface ManifestMeta {
  schema_version: number;
  manifest_id: string;
  manifest_hash: string;
  created_at: string;
  code_commit: string;
  release: {
    release_id: string;
    dataset_fingerprint: string;
    quality_status: string;
    quality_report_fingerprint: string;
    archive_sha256: string;
    p2_splits_fingerprint: string;
    dvc_pointer: Record<string, unknown>;
  };
  seed: number;
  ratios: Record<SplitName, number>;
  tolerance_pp: number;
  classes: ManifestClass[];
  excluded_categories: { category_id: number; category_name: string }[];
  exclusions: ManifestExclusion[];
  counts: ManifestCounts;
}

/** Respuesta de `POST /manifests` (201). */
export interface ManifestCreated {
  manifest_id: string;
  manifest_hash: string;
  counts: ManifestCounts;
}

// --- trabajos de entrenamiento (contrato §4) --------------------------------
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export interface TrainingJob {
  job_id: string;
  kind: 'train' | 'dummy';
  status: JobStatus;
  progress: number;
  config: Record<string, unknown>;
  logs: string[];
  error: string | null;
  worker_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** Se agrega en F4; `null` mientras el run de MLflow no arranca. */
  mlflow_run_id?: string | null;
}

/** Respuesta de `POST /training/jobs` (202). */
export interface JobCreated {
  job_id: string;
  status: JobStatus;
}

/** Experimentos de MLflow válidos (el worker acepta solo estos dos). */
export type ExperimentName = 'p3-clasificador' | 'p3-pruebas';

export interface CreateTrainJobRequest {
  kind: 'train';
  manifest_id: string;
  config: TrainingConfig;
  /** Experimento de MLflow donde registrar el barrido. */
  experiment: ExperimentName;
}

// --- corridas de MLflow (contrato §4) ---------------------------------------
export interface RunSummary {
  run_id: string;
  /** Experimento de MLflow al que pertenece la corrida (para enlazar a su UI). */
  experiment_id: string;
  status: string;
  manifest_id: string;
  params: Record<string, string>;
  best_epoch: number;
  stopped_epoch: number;
  best_val_accuracy: number;
  best_val_loss: number;
  commit: string;
  start_time: string;
  end_time: string;
}

/** Un punto por época de las curvas train/val. */
export interface RunEpoch {
  epoch: number;
  train_loss: number;
  train_accuracy: number;
  val_loss: number;
  val_accuracy: number;
}

export interface RunDetail extends RunSummary {
  history: RunEpoch[];
  artifacts: Record<string, string>;
}

export interface RunsResponse {
  runs: RunSummary[];
}

export interface RunsQuery {
  manifest_id?: string;
  status?: string;
  order_by?: string;
  desc?: boolean;
}

// --- selección del candidato (contrato §5) ----------------------------------
/** `selection.json`: el candidato elegido por validación. Sin métricas de test. */
export interface Selection {
  schema_version: number;
  selected_at: string;
  manifest_id: string;
  manifest_hash: string;
  rule: string;
  candidates: number;
  run_id: string;
  checkpoint_uri: string;
  checkpoint_sha256: string;
  best_epoch: number;
  val_accuracy: number;
  val_loss: number;
}

// --- evaluación en test (contrato §4, F6) ------------------------------------
export interface EvalPerClass {
  class: string;
  precision: number;
  recall: number;
  f1: number;
  support: number;
}

export interface ConfusionMatrix {
  labels: string[];
  /** Filas = clase real, columnas = clase predicha. */
  rows_true_cols_pred: number[][];
}

/** El par de clases que más se confunde en el test (`null` si no hubo errores). */
export interface MostConfused {
  true: string;
  predicted: string;
  count: number;
}

/** Evaluación única en el test congelado. `GET /evaluation` da 409 sin selección. */
export interface EvaluationReport {
  run_id: string;
  manifest_id: string;
  test_size: number;
  accuracy: number;
  passes_threshold: boolean;
  threshold: number;
  f1_macro: number;
  per_class: EvalPerClass[];
  confusion_matrix: ConfusionMatrix;
  majority_baseline: number;
  majority_class: string;
  most_confused?: MostConfused | null;
  evaluated_at: string;
  predictions_uri: string;
  examples_uri: string;
}

/** Un recorte de test con su clase real, la predicha y la probabilidad. */
export interface EvalExample {
  crop_id: string;
  crop_path: string;
  true: string;
  predicted: string;
  probability: number;
}

export interface EvaluationExamples {
  correct: EvalExample[];
  errors: EvalExample[];
}

// --- versiones de modelo (contrato §4/§6, F7) --------------------------------
export interface ModelS3 {
  uri: string;
  version_id: string | null;
  sha256: string;
  /** El objeto realmente existe en S3 con ese SHA-256. */
  exists: boolean;
}

/** Una versión de modelo publicada. La versión es del MODELO, no del dataset. */
export interface ModelEntry {
  version: string;
  run_id: string;
  manifest_id: string;
  release_id: string;
  s3: ModelS3;
  card_uri: string;
}

export interface ModelsResponse {
  active_version: string | null;
  models: ModelEntry[];
}

// --- inferencia (contrato §4, F4/F9) -----------------------------------------
export interface InferenceResult {
  inference_id: string;
  model_version: string;
  predicted_class: string;
  probabilities: Record<string, number>;
  model_sha256: string;
}

export interface AnnotationQueueItem {
  image_id: number;
  status: string;
}

/** Error que conserva el mensaje de la API, no un `fetch failed` generico. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Error de validación de FastAPI: `{loc: [...], msg: "..."}`. */
type ErrorDeValidacion = { loc?: (string | number)[]; msg?: string };

/**
 * Convierte el `detail` de la API en una línea legible.
 *
 * `detail` no siempre es texto. Cuando FastAPI rechaza el cuerpo por el
 * esquema — un `max_cell_share` de 7 cuando es una fracción — devuelve un 422
 * con una LISTA de errores, cada uno con la ruta del campo y su motivo.
 * Tratarlo como cadena daba literalmente `[object Object]` en el banner: el
 * peor mensaje posible, porque el usuario ve que falló y no qué campo. Aquí se
 * aplana a `spatial_bias.max_cell_share: Input should be less than 1`.
 *
 * Se descarta el primer elemento de `loc` (`body`), que nunca aporta nada:
 * todos los campos del PUT vienen del cuerpo.
 */
function mensajeDeError(detail: unknown, status: number): string {
  if (typeof detail === 'string' && detail) return detail;

  if (Array.isArray(detail) && detail.length > 0) {
    const lineas = (detail as ErrorDeValidacion[])
      .map(({ loc, msg }) => {
        const campo = (loc ?? []).filter((parte) => parte !== 'body').join('.');
        return campo && msg ? `${campo}: ${msg}` : (msg ?? '');
      })
      .filter(Boolean);
    if (lineas.length > 0) return lineas.join(' · ');
  }

  return `HTTP ${status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail: unknown;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = body.detail;
    } catch {
      // La respuesta no era JSON: nos quedamos con el codigo de estado.
    }
    throw new ApiError(response.status, mensajeDeError(detail, response.status));
  }
  return (await response.json()) as T;
}

// ---------------------------------------------------------------------------
// Proyecto 4: capturas del dispositivo edge (`Proyecto4/src/p4/capturas`).
// ---------------------------------------------------------------------------

/** Recorte clasificado, en píxeles de la foto. */
export interface RegionCaptura {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Registro guardado: lo que mandó el dispositivo más lo que agrega el receptor. */
export interface CapturaEdge {
  schema_version: number;
  capture_id: string;
  /** ISO 8601 con el offset del dispositivo. */
  captured_at: string;
  predicted_class: string;
  confidence: number;
  device_id: string;
  model_version: string;
  model_sha256: string;
  image_sha256: string;
  image_ref: string;
  region: RegionCaptura | null;
  /** ISO 8601 en UTC, puesto por el receptor. */
  received_at: string;
  image_key: string;
  image_bytes: number;
  image_width: number;
  image_height: number;
}

/** `GET /api/p4/capturas`: de más reciente a más antigua; `errores` = registros ilegibles. */
export interface CapturasRespuesta {
  items: CapturaEdge[];
  total: number;
  errores: { llave: string; problema: string }[];
}

export const api = {
  status: () =>
    request<Record<string, { available: boolean; produced_by: string }>>('/api/status'),
  quality: () => request<Envelope<QualityReport>>('/api/quality'),
  splits: () => request<Envelope<SplitsManifest>>('/api/splits'),
  versions: () => request<Envelope<VersionsManifest>>('/api/versions'),
  exploration: () => request<Envelope<ExplorationManifest>>('/api/exploration'),
  /** URL de la miniatura de una imagen. No es una petición: la resuelve el <image> del SVG. */
  thumbnailUrl: (imageId: number) => `/api/exploration/thumbnail/${imageId}`,
  stats: () => request<Envelope<AnalysisArtifact>>('/api/stats'),
  config: () => request<Config>('/api/config'),
  policy: () => request<PolicyEnvelope>('/api/policy'),
  savePolicy: (data: QualityPolicy) =>
    request<PolicySaved>('/api/policy', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  duplicatesPlan: () => request<DedupePlan>('/api/duplicates/plan'),
  duplicatesRemove: () =>
    request<DedupeResult>('/api/duplicates/remove', { method: 'POST' }),
  pipelineRefresh: () => request<RefreshResult>('/api/pipeline/refresh', { method: 'POST' }),
  copilot: (question: string) =>
    request<CopilotAnswer>('/api/copilot/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    }),

  /** Endpoints del clasificador (Proyecto 3), todos bajo `/api/p3/`. */
  p3: {
    /** Releases; con `approved` solo los que pasaron la compuerta. */
    releases: (approved = true) =>
      request<P3ReleasesResponse>(`/api/p3/releases?approved=${approved}`),
    /** Procedencia de un release aprobado. 409 si la compuerta falló, 404 si no existe. */
    release: (releaseId: string) =>
      request<P3ReleaseDetail>(`/api/p3/releases/${encodeURIComponent(releaseId)}`),
    /** Genera un manifiesto 70/20/10 desde un release aprobado. */
    createManifest: (releaseId: string, seed: number) =>
      request<ManifestCreated>('/api/p3/manifests', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ release_id: releaseId, seed }),
      }),
    manifest: (manifestId: string) =>
      request<ManifestMeta>(`/api/p3/manifests/${encodeURIComponent(manifestId)}`),
    /** Encola un entrenamiento. 422 (config inválida) o 409 (manifiesto) antes de crearlo. */
    createTrainingJob: (body: CreateTrainJobRequest) =>
      request<JobCreated>('/api/p3/training/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    /** Estado, progreso, logs y error de un trabajo (persisten en el servidor). */
    trainingJob: (jobId: string) =>
      request<TrainingJob>(`/api/p3/training/jobs/${encodeURIComponent(jobId)}`),
    /** Corridas de MLflow, filtrables por manifiesto/estado y ordenables. */
    runs: (query: RunsQuery = {}) => request<RunsResponse>(`/api/p3/runs${runsQuery(query)}`),
    run: (runId: string) => request<RunDetail>(`/api/p3/runs/${encodeURIComponent(runId)}`),
    /**
     * Lectura del candidato seleccionado (`selection.json`).
     * NOTA: `contratos.md §4` solo define `POST /selection` (crear); este GET es
     * una adición propuesta para que Experiments muestre el candidato. Coordinar
     * con Edith (F5) antes de congelarlo (regla 11 de AGENTS.md).
     */
    selection: () => request<Selection>('/api/p3/selection'),
    /** Evaluación final en test. Lanza ApiError 409 si la selección no está cerrada. */
    evaluation: () => request<EvaluationReport>('/api/p3/evaluation'),
    /** Aciertos y errores de ejemplo del test (para la galería). */
    evaluationExamples: () => request<EvaluationExamples>('/api/p3/evaluation/examples'),
    /** URL de la miniatura de un recorte. No es una petición: la resuelve el <img>. */
    evaluationCropUrl: (cropId: string) =>
      `/api/p3/evaluation/crops/${encodeURIComponent(cropId)}`,
    /** URL de descarga del CSV de predicciones (no es una petición: la usa un <a>). */
    evaluationPredictionsUrl: () => '/api/p3/evaluation/predictions',
    /** Versiones de modelo publicadas y la versión activa. */
    models: () => request<ModelsResponse>('/api/p3/models'),
    /** URL de la tarjeta (MODEL_CARD.md) de una versión. La usa un `<a>`. */
    modelCardUrl: (version: string) =>
      `/api/p3/models/${encodeURIComponent(version)}/card`,
    /** URL de descarga de los pesos (`model.pt`), contrato C2: el backend verifica el SHA-256. */
    modelWeightsUrl: (version: string) =>
      `/api/p3/models/${encodeURIComponent(version)}/download`,
    /** Marca una versión como activa para inferencia. 404/409/422 si no procede. */
    activateModel: (version: string) =>
      request<{ active_version: string }>(
        `/api/p3/models/${encodeURIComponent(version)}/activate`,
        { method: 'POST' },
      ),
    /** Predice una imagen con la versión activa; `bbox_xywh` recorta antes de predecir. */
    inference: (file: File, bbox?: [number, number, number, number]) => {
      const form = new FormData();
      form.append('file', file);
      if (bbox) form.append('bbox_xywh', JSON.stringify(bbox));
      // Sin Content-Type: el navegador pone el boundary del multipart.
      return request<InferenceResult>('/api/p3/inference', { method: 'POST', body: form });
    },
    /** Envía la imagen de una inferencia a la cola de anotación de P1. */
    sendToAnnotation: (inferenceId: string) =>
      request<{ annotation_queue_item: AnnotationQueueItem }>(
        `/api/p3/inference/${encodeURIComponent(inferenceId)}/send-to-annotation`,
        { method: 'POST' },
      ),
  },

  /** Capturas Edge (Proyecto 4), bajo `/api/p4/capturas`. Solo lectura desde el portal. */
  p4: {
    capturas: (limite = 200) =>
      request<CapturasRespuesta>(`/api/p4/capturas?limite=${limite}`),
    /** La foto la lee el servidor del almacén: el navegador nunca recibe URLs de S3. */
    fotoUrl: (captureId: string) => `/api/p4/capturas/${encodeURIComponent(captureId)}/foto`,
    exportarUrl: (formato: 'csv' | 'json') => `/api/p4/capturas/exportar?formato=${formato}`,
  },
};

/** Arma el query string de `GET /runs` omitiendo lo que no se especificó. */
function runsQuery(query: RunsQuery): string {
  const params = new URLSearchParams();
  if (query.manifest_id) params.set('manifest_id', query.manifest_id);
  if (query.status) params.set('status', query.status);
  if (query.order_by) params.set('order_by', query.order_by);
  if (query.desc !== undefined) params.set('desc', String(query.desc));
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

/**
 * Formatea una metrica segun lo que representa.
 *
 * La direccion de la comparacion no viaja en `CheckResult` — el contrato esta
 * congelado — asi que se deriva del nombre del check. Es el unico punto donde
 * el frontend sabe algo que el contrato no dice.
 */
export function formatMetric(value: number, name: string): string {
  if (name === 'min_images_per_class') return String(Math.round(value));
  if (name === 'class_imbalance') return `${value.toFixed(1)}x`;
  if (name === 'degenerate_boxes' && value >= 1) return String(Math.round(value));
  return `${(value * 100).toFixed(1)}%`;
}

export function comparison(name: string): '>=' | '<=' {
  return name === 'min_images_per_class' ? '>=' : '<=';
}
