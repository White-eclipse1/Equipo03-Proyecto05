import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Pruebas de componente (F8): render y navegación de las páginas de P3.
// Corren aparte del `node:test` de los `.mjs` y del Playwright e2e (`.spec.ts`),
// así cada runner mantiene su alcance. jsdom da un DOM sin navegador real.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.{ts,tsx}'],
    css: false,
  },
});
