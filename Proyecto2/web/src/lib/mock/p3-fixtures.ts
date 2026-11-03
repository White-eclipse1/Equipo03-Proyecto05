/**
 * Datos de ejemplo para el mock backend de P3.
 *
 * Espejan `Proyecto3/docs/contratos.md` y el fixture de 3 clases
 * (`tests/fixtures/p3/`: 10 cat, 9 dog, 9 person). Existen SOLO para que el
 * portal se pueda construir y probar antes de que el backend real esté (regla
 * de calendario de F8: se conecta al backend real el lunes). Nunca deben entrar
 * al build de producción: se importan solo desde `backend.ts`, que a su vez se
 * carga únicamente en desarrollo con `VITE_P3_MOCK=1` o desde las pruebas.
 */

import type {
  EvaluationExamples,
  EvaluationReport,
  ManifestCreated,
  ManifestMeta,
  ModelEntry,
  P3ReleaseDetail,
  P3ReleaseSummary,
  RunDetail,
  RunSummary,
  Selection,
  TrainingConfig,
} from '../api';

/** Marcador único: sirve para probar que estos datos NO están en el build de prod. */
export const MOCK_MARKER = 'P3_MOCK_FIXTURE_DO_NOT_SHIP';

export const RELEASE_ID = '0.1.3';
export const MANIFEST_ID = 'm-0.1.3-s42-1';

const RELEASE_HASH = '2200274dc6bbe6d0bc516e0136ae68651c0040bc6cab64a871794924fa39aa84';

export const releaseSummary: P3ReleaseSummary = {
  release_id: RELEASE_ID,
  dataset_fingerprint: RELEASE_HASH,
  quality_status: 'pass',
  created_at: '2026-09-18T04:17:13Z',
  counts: { images: 2045, annotations: 2120, categories: 5 },
  storage_uri: 's3://dataset-quality-releases-750702272375/0.1.3/dataset.tar.zst',
  published_in: ['dev', 'prod'],
  trainable: true,
  blocked_reason: null,
  manifests: [
    { manifest_id: 'm-0.1.3-s42-1', seed: 42, sweep: true },
    { manifest_id: 'm-0.1.3-s7-1', seed: 7, sweep: false },
  ],
};

export const releaseDetail: P3ReleaseDetail = {
  ...releaseSummary,
  quality_report_fingerprint: '4d6e64aa13c6f66b15801811c4bb84ebc265b07f538ae27982f79628b170631a',
  archive_sha256: '787742988af1df41d9a58573b81b5c9b4fe7ab24a647b25f2e71d3eb323838b5',
};

// La lista REAL que devuelve la API (`GET /releases?approved=true`), en orden:
// 0.1.1 (sin archive_sha256 -> no entrenable), 0.1.2 (no publicado en prod -> no
// entrenable), 0.1.3 (entrenable). Es el dato de la prueba de regresión M1.
const release011: P3ReleaseSummary = {
  release_id: '0.1.1',
  dataset_fingerprint: '295f4257328ee413ca6d7b8e9446bae50f7db80b2777bb8b93eb3f1dbc3dbdf2',
  quality_status: 'pass',
  created_at: '2026-09-15T01:14:15Z',
  counts: { images: 838, annotations: 887, categories: 5 },
  storage_uri: null,
  published_in: ['dev'],
  trainable: false,
  blocked_reason: 'no registra archive_sha256',
  manifests: [],
};

const release012: P3ReleaseSummary = {
  release_id: '0.1.2',
  dataset_fingerprint: '2200274dc6bbe6d0bc516e0136ae68651c0040bc6cab64a871794924fa39aa84',
  quality_status: 'pass',
  created_at: '2026-09-18T04:14:00Z',
  counts: { images: 2045, annotations: 2120, categories: 5 },
  storage_uri: null,
  published_in: ['dev'],
  trainable: false,
  blocked_reason: 'sin manifiesto congelado',
  manifests: [],
};

/** Lo que responde `GET /releases?approved=true`, en orden. */
export const releaseSummaries: P3ReleaseSummary[] = [release011, release012, releaseSummary];

// Hashes reales de `Proyecto2/reports/versions.json`.
const releaseDetailsById: Record<string, P3ReleaseDetail> = {
  '0.1.1': {
    ...release011,
    quality_report_fingerprint:
      'd2cd9e197f4e8870d99aa923d849e220cb5b5c4317ef31db25695d7533af3432',
    archive_sha256: null,
  },
  '0.1.2': {
    ...release012,
    quality_report_fingerprint:
      '512fc1c3460ef905b3d73270ce206679c5ac0aab243cf1236ab8fff5c208fe09',
    archive_sha256: '130998b0c1303a35634417aad5376bd691e34657ced4d55351d547b680912f60',
  },
  '0.1.3': releaseDetail,
};

export function releaseDetailFor(releaseId: string): P3ReleaseDetail | undefined {
  return releaseDetailsById[releaseId];
}

export const manifestMeta: ManifestMeta = {
  schema_version: 1,
  manifest_id: MANIFEST_ID,
  manifest_hash: 'b1a2c3d4e5f60718293a4b5c6d7e8f900112233445566778899aabbccddeeff0',
  created_at: '2026-09-25T18:00:00Z',
  code_commit: '0000000000000000000000000000000000000000',
  release: {
    release_id: RELEASE_ID,
    dataset_fingerprint: RELEASE_HASH,
    quality_status: 'pass',
    quality_report_fingerprint: releaseDetail.quality_report_fingerprint,
    // El manifiesto deriva de un release empaquetado: su archive siempre existe.
    archive_sha256: releaseDetail.archive_sha256 as string,
    p2_splits_fingerprint: '9a87e0de3fb3069f06686065f149d64787593c04d90265a3e0f667a170d66279',
    dvc_pointer: {
      path: 'Proyecto2/data/raw.dvc',
      md5: 'ca56420c9992f8b75fdb10f2ece81704.dir',
      nfiles: 2046,
      size: 634490876,
    },
  },
  seed: 42,
  ratios: { train: 0.7, val: 0.2, test: 0.1 },
  tolerance_pp: 5,
  classes: [
    { class_index: 0, category_id: 4, category_name: 'cat' },
    { class_index: 1, category_id: 3, category_name: 'dog' },
    { class_index: 2, category_id: 2, category_name: 'person' },
  ],
  excluded_categories: [
    { category_id: 1, category_name: 'car' },
    { category_id: 5, category_name: 'bicycle' },
  ],
  exclusions: [
    { annotation_id: 77, source_image_id: 40, reason: 'degenerate_bbox' },
    { annotation_id: 91, source_image_id: 52, reason: 'bbox_out_of_bounds' },
    { annotation_id: 12, source_image_id: 9, reason: 'missing_image' },
  ],
  // Recortes válidos del fixture: 10 cat, 9 dog, 9 person = 28.
  counts: {
    crops: {
      train: { cat: 7, dog: 6, person: 6 },
      val: { cat: 2, dog: 2, person: 2 },
      test: { cat: 1, dog: 1, person: 1 },
    },
    originals: {
      train: { cat: 7, dog: 6, person: 6 },
      val: { cat: 2, dog: 2, person: 2 },
      test: { cat: 1, dog: 1, person: 1 },
    },
  },
};

/** La config efectiva que reportan las corridas (varía el learning_rate por corrida). */
function paramsFor(index: number): Record<string, string> {
  const optimizers = ['adamw', 'adam', 'sgd'];
  const config: TrainingConfig = {
    optimizer: (optimizers[index % 3] ?? 'adamw') as TrainingConfig['optimizer'],
    batch_size: index % 2 === 0 ? 32 : 64,
    max_epochs: 30,
    learning_rate: Number((0.0001 * (1 + (index % 5))).toFixed(5)),
    image_size: 224,
    hidden_layers: index % 2 === 0 ? [256] : [512, 128],
    dropout: 0.3,
    seed: 42 + index,
    patience: 5,
    min_delta: 0.001,
    monitor_metric: 'val_accuracy',
  };
  return Object.fromEntries(
    Object.entries(config).map(([key, value]) => [
      key,
      Array.isArray(value) ? JSON.stringify(value) : String(value),
    ]),
  );
}

/** 12 corridas FINISHED deterministas sobre el manifiesto, con accuracy única. */
export const runs: RunSummary[] = Array.from({ length: 12 }, (_, i) => {
  // Valores únicos (0.70 … 0.92) para que el orden por val_accuracy sea estable.
  const bestValAccuracy = Number((0.7 + i * 0.02).toFixed(2));
  const bestEpoch = 8 + (i % 7);
  return {
    run_id: `run${String(i + 1).padStart(4, '0')}${'0'.repeat(24)}`,
    experiment_id: '1',
    status: 'FINISHED',
    manifest_id: MANIFEST_ID,
    params: paramsFor(i),
    best_epoch: bestEpoch,
    stopped_epoch: bestEpoch + 5,
    best_val_accuracy: bestValAccuracy,
    best_val_loss: Number((0.9 - bestValAccuracy * 0.6).toFixed(4)),
    commit: '0000000000000000000000000000000000000000',
    start_time: `2026-09-28T1${i % 10}:00:00Z`,
    end_time: `2026-09-28T1${i % 10}:20:00Z`,
  };
});

/** Curvas por época derivadas del mejor accuracy: sube val, baja loss. */
export function runDetail(run: RunSummary): RunDetail {
  const epochs = run.stopped_epoch;
  const history = Array.from({ length: epochs }, (_, e) => {
    const t = (e + 1) / epochs;
    const valAcc = Number((run.best_val_accuracy * (0.6 + 0.4 * t)).toFixed(4));
    return {
      epoch: e + 1,
      train_loss: Number((1.1 * (1 - 0.8 * t)).toFixed(4)),
      train_accuracy: Number(Math.min(0.99, valAcc + 0.05).toFixed(4)),
      val_loss: Number((1.0 * (1 - 0.7 * t)).toFixed(4)),
      val_accuracy: valAcc,
    };
  });
  return {
    ...run,
    history,
    artifacts: {
      curves: `mlflow-artifacts:/${run.run_id}/curves.png`,
      checkpoint: `mlflow-artifacts:/${run.run_id}/checkpoints/best.pt`,
    },
  };
}

/** El candidato: la corrida de mayor val_accuracy (desempate por menor val_loss). */
const bestRun = runs.reduce((best, run) =>
  run.best_val_accuracy > best.best_val_accuracy ||
  (run.best_val_accuracy === best.best_val_accuracy && run.best_val_loss < best.best_val_loss)
    ? run
    : best,
);

export const selection: Selection = {
  schema_version: 1,
  selected_at: '2026-09-29T18:00:00Z',
  manifest_id: MANIFEST_ID,
  manifest_hash: manifestMeta.manifest_hash,
  rule: 'max val_accuracy; desempate min val_loss; luego end_time mas temprano',
  candidates: runs.length,
  run_id: bestRun.run_id,
  checkpoint_uri: `mlflow-artifacts:/${bestRun.run_id}/checkpoints/best.pt`,
  checkpoint_sha256: 'c0ffee00000000000000000000000000000000000000000000000000000000ab',
  best_epoch: bestRun.best_epoch,
  val_accuracy: bestRun.best_val_accuracy,
  val_loss: bestRun.best_val_loss,
};

// Evaluacion en el test congelado del candidato (F6). Supera el umbral de 0.85.
export const evaluation: EvaluationReport = {
  run_id: bestRun.run_id,
  manifest_id: MANIFEST_ID,
  test_size: 30,
  accuracy: 0.8667,
  passes_threshold: true,
  threshold: 0.85,
  f1_macro: 0.8631,
  per_class: [
    { class: 'cat', precision: 0.9, recall: 0.9, f1: 0.9, support: 10 },
    { class: 'dog', precision: 0.818, recall: 0.9, f1: 0.857, support: 10 },
    { class: 'person', precision: 0.889, recall: 0.8, f1: 0.842, support: 10 },
  ],
  confusion_matrix: {
    labels: ['cat', 'dog', 'person'],
    rows_true_cols_pred: [
      [9, 1, 0],
      [0, 9, 1],
      [1, 1, 8],
    ],
  },
  majority_baseline: 0.3333,
  majority_class: 'cat',
  // Con esta matriz todos los errores valen 1; el backend desempata alfabético
  // por (real, predicho), así que el par más confundido es cat → dog (no person → cat).
  most_confused: { true: 'cat', predicted: 'dog', count: 1 },
  evaluated_at: '2026-09-29T19:00:00Z',
  predictions_uri: '/api/p3/evaluation/predictions',
  examples_uri: '/api/p3/evaluation/examples',
};

export const evaluationExamples: EvaluationExamples = {
  correct: [
    { crop_id: '0.1.3:a4', crop_path: 'a4.png', true: 'cat', predicted: 'cat', probability: 0.97 },
    { crop_id: '0.1.3:a9', crop_path: 'a9.png', true: 'dog', predicted: 'dog', probability: 0.91 },
    { crop_id: '0.1.3:a6', crop_path: 'a6.png', true: 'person', predicted: 'person', probability: 0.88 },
  ],
  errors: [
    { crop_id: '0.1.3:a17', crop_path: 'a17.png', true: 'person', predicted: 'cat', probability: 0.55 },
    { crop_id: '0.1.3:a39', crop_path: 'a39.png', true: 'dog', predicted: 'person', probability: 0.52 },
  ],
};

// Versiones de modelo publicadas. La versión es del MODELO (semver), distinta de
// la del dataset (release_id). 0.8.0 tiene el objeto ausente en S3 a propósito
// (para probar que no se puede activar). La activa por defecto es 1.0.0.
const BUCKET_URI = 's3://dataset-quality-releases-750702272375/models/clasificador';
export const DEFAULT_ACTIVE_VERSION = '1.0.0';

export const modelVersions: ModelEntry[] = [
  {
    version: '0.9.0',
    run_id: runs[8]?.run_id ?? 'run0009',
    manifest_id: MANIFEST_ID,
    release_id: RELEASE_ID,
    s3: { uri: `${BUCKET_URI}/0.9.0/model.pt`, version_id: 'v0900', sha256: `a9${'0'.repeat(62)}`, exists: true },
    card_uri: `${BUCKET_URI}/0.9.0/MODEL_CARD.md`,
  },
  {
    version: '1.0.0',
    run_id: bestRun.run_id,
    manifest_id: MANIFEST_ID,
    release_id: RELEASE_ID,
    s3: { uri: `${BUCKET_URI}/1.0.0/model.pt`, version_id: 'v1000', sha256: `10${'0'.repeat(62)}`, exists: true },
    card_uri: `${BUCKET_URI}/1.0.0/MODEL_CARD.md`,
  },
  {
    version: '0.8.0',
    run_id: runs[2]?.run_id ?? 'run0003',
    manifest_id: MANIFEST_ID,
    release_id: RELEASE_ID,
    s3: { uri: `${BUCKET_URI}/0.8.0/model.pt`, version_id: null, sha256: `08${'0'.repeat(62)}`, exists: false },
    card_uri: `${BUCKET_URI}/0.8.0/MODEL_CARD.md`,
  },
];

/** Segundo manifiesto congelado de 0.1.3 (seed 7), con sus conteos reales (F12). */
export const MANIFEST_ID_SEED_7 = 'm-0.1.3-s7-1';
export const manifestSeed7: ManifestCreated = {
  manifest_id: MANIFEST_ID_SEED_7,
  manifest_hash: 'c7319207ae60b636e8ef45cd0a6f904e3c2b07755e9536fd2eded140a5089f01',
  counts: {
    crops: {
      train: { cat: 230, dog: 275, person: 515 },
      val: { cat: 67, dog: 69, person: 155 },
      test: { cat: 32, dog: 35, person: 81 },
    },
    originals: {
      train: { cat: 219, dog: 252, person: 304 },
      val: { cat: 63, dog: 63, person: 93 },
      test: { cat: 30, dog: 33, person: 44 },
    },
  },
};
