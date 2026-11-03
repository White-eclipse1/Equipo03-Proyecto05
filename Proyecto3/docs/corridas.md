# Corridas del barrido — F5 T13

Experimento `p3-clasificador` en MLflow, manifiesto congelado `m-0.1.3-s42-1` (`45600f297d13…`), clases `cat`, `dog`, `person`. Configuraciones de [`config/sweep.yaml`](../config/sweep.yaml), lanzadas por el worker con `scripts/launch_sweep.py`. Generado por `scripts/close_sweep.py` desde la API de MLflow el 2026-09-27 03:39 UTC. **Ninguna métrica de test.**

## Corridas válidas (12 FINISHED)

| Corrida | run_id | optimizer | batch | max_epochs | lr | image | hidden | dropout | mejor época | parada | best val_acc | best val_loss |
|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|
| r01 | `c15c8edf712845a28fdd64e6126907cd` | adamw | 32 | 30 | 0.0003 | 224 | `[256]` | 0.3 | 5 | 10 | 0.9726 | 0.0745 |
| r02 | `eab4973504304baab61a74c93c577a18` | adamw | 64 | 30 | 0.001 | 224 | `[512, 128]` | 0.5 | 7 | 12 | 0.9384 | 0.1641 |
| r04 | `46cb41fb9ac744c0a9715771a5a2d0b4` | adam | 64 | 30 | 0.0003 | 128 | `[]` | 0.2 | 11 | 16 | 0.9829 | 0.0331 |
| r06 | `ba8aac02ee2a454f93d8dcb55e6df17f` | sgd | 64 | 15 | 0.003 | 128 | `[512, 128]` | 0.2 | 6 | 11 | 0.9897 | 0.0473 |
| r07 | `cb72f7db6b704936bc67f9003a9915eb` | adamw | 32 | 15 | 0.0003 | 128 | `[512, 128]` | 0.5 | 3 | 8 | 0.9623 | 0.1078 |
| r08 | `5ebc2c9f94fa491e9e9adc7b7c8184ac` | sgd | 32 | 30 | 0.001 | 224 | `[]` | 0.3 | 3 | 8 | 0.9966 | 0.0435 |
| r09 | `76dc45e27ea14f788b80bd0f11c261ae` | adam | 32 | 30 | 0.001 | 224 | `[512, 128]` | 0.3 | 7 | 12 | 0.9418 | 0.1702 |
| r10 | `9f9b62c202f0446a8a4b411a10321eff` | adamw | 64 | 15 | 0.0001 | 224 | `[]` | 0.5 | 6 | 11 | 0.9966 | 0.0243 |
| r11 | `75d6bbb929514958916d2eb1e0926db0` | sgd | 64 | 30 | 0.01 | 128 | `[256]` | 0.3 | 4 | 9 | 0.9760 | 0.1131 |
| r12 | `26afad93fe5244f69a4aab0c01518b31` | adamw | 32 | 30 | 0.0001 | 160 | `[256]` | 0.2 | 2 | 7 | 0.9897 | 0.0412 |
| r03 | `16c09c8e26fd4e2fa8453f96dfb11af8` | adam | 32 | 15 | 0.0001 | 224 | `[256]` | 0.2 | 7 | 12 | 0.9932 | 0.0292 |
| r05 | `981df1d9a8344c589eeedaa56f30ac76` | sgd | 32 | 30 | 0.01 | 224 | `[256]` | 0.5 | 5 | 10 | 0.9760 | 0.0724 |

Valores por parámetro: `optimizer` ['adam', 'adamw', 'sgd']; `batch_size` ['32', '64']; `max_epochs` ['15', '30']; `learning_rate` ['0.0001', '0.0003', '0.001', '0.003', '0.01']; `image_size` ['128', '160', '224']; `hidden_layers` ['[256]', '[512, 128]', '[]']; `dropout` ['0.2', '0.3', '0.5']

## Corridas no válidas (2)

- `1e05d6ac9da64cfcaad6672793183bbf` (r05): FAILED — interrumpida por un corte de luz; relanzada como otro trabajo
- `3d471e3c0b5c4a4cad8d3341ec589c37` (r03): FAILED — interrumpida por un corte de luz; relanzada como otro trabajo

## Comprobación 3.1

- OK: >= 10 corridas FINISHED, los 7 parámetros con >= 2 valores, resultados distintos, mismo manifiesto
