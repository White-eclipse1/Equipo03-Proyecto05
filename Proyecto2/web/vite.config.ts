import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// En desarrollo la API corre aparte (uvicorn); en produccion FastAPI sirve
// este mismo build desde `src/dataset_quality/static/`.
const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000';
const proxy = Object.fromEntries(
  ['/api', '/health', '/docs', '/openapi.json'].map((path) => [
    path,
    { target: apiTarget, changeOrigin: true },
  ]),
);

export default defineConfig({
  plugins: [react()],
  server: { host: '0.0.0.0', port: 5273, strictPort: true, proxy },
  build: { outDir: '../src/dataset_quality/static', emptyOutDir: false },
});
