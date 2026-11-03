/**
 * Settings: que guardar la política la escriba de verdad, y que sobreviva.
 *
 * Es la única pantalla que ESCRIBE, y `PUT /api/policy` reescribe el
 * `quality.yaml` del repositorio — el mismo archivo que lee `dq gate`. Por eso
 * estas pruebas guardan la política original antes de tocar nada y la
 * reponen en `afterAll` pase lo que pase: una prueba que deja el umbral de la
 * compuerta movido es peor que no tenerla.
 *
 * "Persistencia" aquí significa lo que significa para el usuario: que el valor
 * siga ahí después de recargar el navegador. Comprobar solo que el estado de
 * React cambió probaría el formulario, no el guardado.
 */

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/** Campo elegido para las pruebas: la rejilla del sesgo espacial. */
const CAMPO = 'spatial_bias.grid_size';
const VALOR_DE_PRUEBA = '4';

type Politica = Record<string, unknown>;

let original: Politica;

/** Lee la política vigente por la API, sin pasar por la interfaz. */
async function leerPolitica(request: APIRequestContext): Promise<Politica> {
  const respuesta = await request.get('/api/policy');
  expect(respuesta.status()).toBe(200);
  return (await respuesta.json()).data as Politica;
}

async function escribirPolitica(request: APIRequestContext, politica: Politica) {
  const respuesta = await request.put('/api/policy', { data: politica });
  expect(respuesta.status(), await respuesta.text()).toBe(200);
}

async function abrirSettings(page: Page) {
  await page.goto('/#/settings');
  await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
  await expect(page.getByLabel(CAMPO)).toBeVisible({ timeout: 15_000 });
}

test.beforeAll(async ({ playwright, baseURL }) => {
  const request = await playwright.request.newContext({ baseURL });
  original = await leerPolitica(request);
  await request.dispose();
});

test.afterAll(async ({ playwright, baseURL }) => {
  // Incondicional: si una prueba falló a mitad de un guardado, esta es la
  // única red que evita dejar `quality.yaml` con un umbral de prueba.
  const request = await playwright.request.newContext({ baseURL });
  await escribirPolitica(request, original);
  const repuesta = await leerPolitica(request);
  expect(repuesta).toEqual(original);
  await request.dispose();
});

test('la política se carga desde quality.yaml en el formulario', async ({
  page,
  request,
}, testInfo) => {
  await abrirSettings(page);

  const enDisco = await leerPolitica(request);
  const enPantalla = await page.getByLabel(CAMPO).inputValue();

  // El formulario no inventa valores por defecto: enseña el archivo.
  expect(enPantalla).toBe(
    String((enDisco.spatial_bias as Record<string, unknown>).grid_size),
  );

  await testInfo.attach('settings-politica-cargada', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });
});

test('guardar escribe en quality.yaml y el valor sobrevive a una recarga', async ({
  page,
  request,
}, testInfo) => {
  await abrirSettings(page);

  const guardar = page.getByRole('button', { name: /guardar política/i });
  // Sin cambios el botón está deshabilitado: no se guarda por accidente.
  await expect(guardar).toBeDisabled();

  await page.getByLabel(CAMPO).fill(VALOR_DE_PRUEBA);
  await expect(guardar).toBeEnabled();
  await expect(page.getByText('sin guardar')).toBeVisible();

  const respuesta = page.waitForResponse(
    (r) => r.url().includes('/api/policy') && r.request().method() === 'PUT',
  );
  await guardar.click();
  expect((await respuesta).status()).toBe(200);

  // 1. La pantalla confirma qué cambió, nombrando el campo.
  await expect(page.getByText(new RegExp(`Guardado en.*quality\\.yaml`, 'i'))).toBeVisible();
  await expect(page.getByText(new RegExp(CAMPO.replace('.', '\\.')))).toBeVisible();

  await testInfo.attach('settings-guardado', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });

  // 2. El archivo en disco tiene el valor nuevo, no solo el estado de React.
  const enDisco = await leerPolitica(request);
  expect((enDisco.spatial_bias as Record<string, unknown>).grid_size).toBe(
    Number(VALOR_DE_PRUEBA),
  );

  // 3. Y sobrevive a recargar el navegador entero, que es la prueba real de
  //    persistencia: un estado que solo vive en memoria muere aquí.
  await page.reload();
  await expect(page.getByLabel(CAMPO)).toHaveValue(VALOR_DE_PRUEBA, { timeout: 15_000 });
});

test('avisa cuando el umbral guardado incumple el mínimo del curso', async ({ page }) => {
  await abrirSettings(page);

  // Bajar `min_images` por debajo de 300 se permite — hay que poder probar la
  // compuerta — pero no en silencio: el servidor devuelve un aviso y la
  // pantalla lo enseña. Un guardado peligroso que no avisa es el fallo que
  // esta prueba impide.
  await page.getByLabel('min_images_per_class.min_images').fill('5');
  await page.getByRole('button', { name: /guardar política/i }).click();

  await expect(page.getByText(/por debajo de las 300 imagenes/i)).toBeVisible();
  await expect(page.getByText(/test_min_images\.py/i)).toBeVisible();
});

test('un umbral inválido se rechaza con un 422 que nombra el campo', async ({ page }) => {
  await abrirSettings(page);

  // `max_cell_share` es una fracción: 7 está fuera de rango. El servidor lo
  // rechaza y la pantalla enseña su mensaje en vez de escribir basura.
  await page.getByLabel('spatial_bias.max_cell_share').fill('7');

  const respuesta = page.waitForResponse(
    (r) => r.url().includes('/api/policy') && r.request().method() === 'PUT',
  );
  await page.getByRole('button', { name: /guardar política/i }).click();

  expect((await respuesta).status()).toBe(422);
  await expect(page.locator('.banner.fail')).toContainText(/max_cell_share/i);
});
