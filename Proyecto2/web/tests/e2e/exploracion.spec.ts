/**
 * La proyección PCA: el hover que enseña la miniatura y el filtro de la leyenda.
 *
 * Son las dos interacciones de la pantalla, y las dos son invisibles para una
 * prueba de unidad: viven en el SVG, dependen de eventos de ratón y de que el
 * endpoint de miniaturas responda. Si `ScatterPlot` dejara de pasar
 * `thumbnailUrl`, o si la leyenda dejara de atenuar los puntos de las demás
 * clases, todo seguiría compilando y renderizando — y la pantalla no serviría
 * para lo que existe.
 */

import { expect, test, type Page } from '@playwright/test';

async function abrirExploracion(page: Page) {
  await page.goto('/#/exploration');
  await expect(page.getByRole('heading', { name: 'Exploración', level: 1 })).toBeVisible();
  // El scatter se dibuja cuando el manifiesto llegó; sin esperar, el primer
  // `hover` caería sobre un SVG todavía vacío.
  await expect(page.locator('svg circle').first()).toBeVisible({ timeout: 15_000 });
}

test('la proyección dibuja un punto por imagen', async ({ page }) => {
  await abrirExploracion(page);

  const puntos = page.locator('svg circle');
  const dibujados = await puntos.count();

  // El tile de la cabecera dice cuántas imágenes se proyectaron; el SVG tiene
  // que tener exactamente esos círculos. Es lo que atrapa una proyección
  // truncada, que a simple vista parece una nube legítima.
  const rotulo = await page.locator('.tiles').getByText(/^\d+$/).first().innerText();
  expect(dibujados).toBe(Number(rotulo));
  expect(dibujados).toBeGreaterThan(0);
});

test('al posar el ratón sobre un punto aparece su miniatura', async ({ page }, testInfo) => {
  const miniaturas: number[] = [];
  page.on('response', (respuesta) => {
    if (new URL(respuesta.url()).pathname.includes('/thumbnail')) {
      miniaturas.push(respuesta.status());
    }
  });

  await abrirExploracion(page);

  // Antes del hover no hay ninguna vista previa.
  await expect(page.locator('svg image')).toHaveCount(0);

  // `force` porque con 2045 puntos el primer círculo casi siempre tiene otro
  // encima, y la comprobación de accionabilidad de Playwright se niega a
  // interactuar con un elemento tapado. No se está esquivando un fallo de la
  // app: el ratón se mueve de verdad a esa coordenada y el círculo que esté
  // arriba recibe el evento, que es exactamente lo que hace un usuario. Qué
  // círculo concreto sea no le importa a esta prueba.
  await page.locator('svg circle').first().hover({ force: true });

  const previa = page.locator('svg image');
  await expect(previa).toHaveCount(1);

  // La miniatura apunta al endpoint del backend, no a un placeholder.
  const href = await previa.getAttribute('href');
  expect(href).toContain('/api/');

  await testInfo.attach('pca-hover-miniatura', {
    body: await page.screenshot(),
    contentType: 'image/png',
  });

  // Y el backend la sirvió: una miniatura rota dejaría el `<image>` en el DOM
  // igualmente, así que comprobar solo el DOM no bastaría.
  await expect
    .poll(() => miniaturas.length, { timeout: 10_000 })
    .toBeGreaterThan(0);
  expect(miniaturas.every((estado) => estado === 200)).toBe(true);
});

test('al quitar el ratón la miniatura desaparece', async ({ page }) => {
  await abrirExploracion(page);

  await page.locator('svg circle').first().hover({ force: true });
  await expect(page.locator('svg image')).toHaveCount(1);

  // Se mueve el ratón fuera del gráfico, al encabezado de la página.
  await page.getByRole('heading', { name: 'Exploración', level: 1 }).hover();

  await expect(page.locator('svg image')).toHaveCount(0);
});

test('la leyenda aísla una clase y "todas" la restaura', async ({ page }, testInfo) => {
  await abrirExploracion(page);

  const opacidades = () =>
    page.locator('svg circle').evaluateAll((nodos) =>
      nodos.map((nodo) => Number((nodo as SVGCircleElement).getAttribute('opacity'))),
    );

  const inicial = await opacidades();
  // Sin filtro ninguno está atenuado: todos comparten la misma opacidad.
  expect(new Set(inicial).size).toBe(1);

  // La primera clase real de la leyenda ("todas" es el botón de reset).
  const botones = page.locator('.card button');
  const clase = botones.nth(1);
  const nombreClase = (await clase.innerText()).trim();
  await clase.click();

  const filtrado = await opacidades();
  const atenuados = filtrado.filter((valor) => valor < 0.5).length;
  const visibles = filtrado.filter((valor) => valor >= 0.5).length;

  expect(atenuados, `ningún punto se atenuó al aislar ${nombreClase}`).toBeGreaterThan(0);
  expect(visibles, `se atenuaron todos los puntos al aislar ${nombreClase}`).toBeGreaterThan(0);
  expect(atenuados + visibles).toBe(inicial.length);

  await testInfo.attach(`pca-filtro-${nombreClase}`, {
    body: await page.screenshot(),
    contentType: 'image/png',
  });

  // Volver a pulsar la misma clase deshace el aislamiento.
  await clase.click();
  expect(new Set(await opacidades()).size).toBe(1);

  // Y el botón "todas" también, viniendo de otra clase aislada.
  await clase.click();
  await botones.first().click();
  expect(new Set(await opacidades()).size).toBe(1);
});
