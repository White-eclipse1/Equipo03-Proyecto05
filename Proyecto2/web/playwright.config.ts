/**
 * Pruebas de navegador contra la app REAL, no contra mocks.
 *
 * Es una decisión deliberada y tiene un coste: hay que levantar el entorno
 * (`python scripts/up.py`) antes de correrlas. A cambio, lo que se comprueba es
 * lo que se entrega — que las siete pantallas piden sus artefactos al backend y
 * los reciben con 200, que la proyección responde al ratón, y que guardar la
 * política la escribe de verdad en `quality.yaml`. Interceptando las respuestas
 * con `page.route` nada de eso se probaría: se probaría el mock.
 *
 * `DQ_BASE_URL` permite apuntarlas a otro host (CI las deja en el de por
 * defecto, que es el puerto que publica `docker-compose.yml`).
 */

import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.DQ_BASE_URL ?? 'http://localhost:8000';

export default defineConfig({
  testDir: './tests/e2e',
  // Las pruebas de política escriben en `quality.yaml`, que es un archivo
  // compartido: en paralelo se pisarían entre sí. El resto son de lectura y
  // rápidas, así que serializar todo sale más barato que aislar el estado.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },

  // El reporte HTML es la evidencia que se entrega; se escribe fuera de `web/`
  // para que viva junto al resto de artefactos de evaluación.
  //
  // Solo HTML: el reporter `json` vuelve a incrustar las mismas capturas en
  // base64 y añadía 1.6 MB duplicados a cada corrida, que en un repositorio se
  // acumulan commit a commit sin aportar nada que el HTML no tenga.
  reporter: [['list'], ['html', { outputFolder: '../reports/evaluation/playwright', open: 'never' }]],

  use: {
    baseURL,
    // Captura SIEMPRE, no solo al fallar: la retroalimentación pide un reporte
    // con capturas de las siete pantallas, y una captura que solo existe
    // cuando algo se rompe no sirve como evidencia de que algo funciona.
    screenshot: 'on',
    trace: 'retain-on-failure',
    video: 'off',
  },

  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
