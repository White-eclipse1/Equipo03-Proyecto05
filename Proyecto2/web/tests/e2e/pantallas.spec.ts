/**
 * Las siete pantallas cargan, y cargan con datos del backend.
 *
 * El error que esta suite existe para atrapar: una pantalla que renderiza su
 * encabezado y sus tarjetas vacías porque el `fetch` devolvió 500 y el estado
 * de error se quedó a medio pintar. Por eso cada caso comprueba DOS cosas —
 * que el contenido propio de la pantalla está, y que todas las respuestas de
 * `/api/` que pidió fueron 200 — y no solo que el `<h1>` existe.
 */

import { expect, test, type Page, type Response } from '@playwright/test';

/** Las siete de `App.tsx`, en el orden en que aparecen en la barra lateral. */
const PANTALLAS = [
  { id: 'overview', boton: 'Overview', titulo: 'Dataset overview' },
  { id: 'analyzers', boton: 'Analyzers', titulo: 'Analyzers' },
  { id: 'splits', boton: 'Splits', titulo: 'Splits' },
  { id: 'versions', boton: 'Versions', titulo: 'Versions' },
  { id: 'copilot', boton: 'Copilot', titulo: 'Dataset Copilot' },
  // El id de la ruta y la etiqueta del boton no coinciden en esta: la ruta es
  // `#/exploration` y el boton dice "Exploración".
  { id: 'exploration', boton: 'Exploración', titulo: 'Exploración' },
  { id: 'settings', boton: 'Settings', titulo: 'Settings' },
] as const;

/**
 * Registra el código de estado de cada respuesta de la API.
 *
 * Se engancha antes de navegar porque las pantallas piden sus artefactos
 * durante el primer render: suscribirse después perdería justo las llamadas
 * que interesan.
 */
function observarApi(page: Page): Map<string, number> {
  const respuestas = new Map<string, number>();
  page.on('response', (respuesta: Response) => {
    const url = new URL(respuesta.url());
    if (url.pathname.startsWith('/api/')) {
      respuestas.set(url.pathname + url.search, respuesta.status());
    }
  });
  return respuestas;
}

/**
 * La pantalla terminó de resolver y no se quedó en un error.
 *
 * No vale contar `.state`: esa clase la comparten el "Cargando…", el error y
 * los vacíos legítimos — una gráfica sin datos que pinta "Sin datos." es una
 * pantalla sana. Lo que no puede quedar es el cargando ni el error, así que se
 * busca su texto, que sí los distingue.
 */
async function esperarAQueResuelva(page: Page) {
  await expect(page.getByText('Cargando…')).toHaveCount(0, { timeout: 15_000 });
  await expect(page.getByText('No se pudo cargar la información.')).toHaveCount(0);
}

for (const pantalla of PANTALLAS) {
  test(`la pantalla ${pantalla.id} carga con datos del backend`, async ({ page }, testInfo) => {
    const respuestas = observarApi(page);

    await page.goto(`/#/${pantalla.id}`);

    await expect(page.getByRole('heading', { name: pantalla.titulo, level: 1 })).toBeVisible();

    // Copilot no pide nada al abrirse (es un formulario), así que no se le
    // exige haber consultado la API; a las demás sí.
    if (pantalla.id !== 'copilot') {
      await esperarAQueResuelva(page);
      expect(respuestas.size, `${pantalla.id} no consultó ningún artefacto`).toBeGreaterThan(0);
    }

    const noDoscientos = [...respuestas.entries()].filter(([, estado]) => estado !== 200);
    expect(noDoscientos, `respuestas != 200 en ${pantalla.id}`).toEqual([]);

    // La captura se adjunta al reporte HTML con el nombre de la pantalla, que
    // es lo que la vuelve revisable de un vistazo.
    await testInfo.attach(`pantalla-${pantalla.id}`, {
      body: await page.screenshot({ fullPage: true }),
      contentType: 'image/png',
    });
  });
}

test('la barra lateral navega entre las siete sin recargar la página', async ({ page }) => {
  await page.goto('/#/overview');

  // Una marca en `window` que sobrevive a la navegación por hash pero no a una
  // recarga: si el router hiciera un full reload, desaparecería.
  await page.evaluate(() => {
    (window as unknown as { __marca?: number }).__marca = 42;
  });

  for (const pantalla of PANTALLAS) {
    await page.getByRole('button', { name: pantalla.boton, exact: true }).click();
    await expect(page.getByRole('heading', { name: pantalla.titulo, level: 1 })).toBeVisible();
  }

  const marca = await page.evaluate(
    () => (window as unknown as { __marca?: number }).__marca,
  );
  expect(marca, 'la navegación recargó la página en vez de enrutar por hash').toBe(42);
});

test('una pantalla dice que algo falta en vez de pintar tarjetas vacías', async ({ page }) => {
  // El backend responde 503 cuando un artefacto no se ha generado todavía. La
  // pantalla tiene que decirlo con todas las letras; el fallo silencioso —
  // encabezado correcto y cuerpo en blanco — es el que engaña.
  await page.route('**/api/versions', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Todavia no existe `versions.json`.' }),
    }),
  );

  await page.goto('/#/versions');

  await expect(page.getByText(/versions\.json/i)).toBeVisible();
});
