import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

// Mock backend de P3 SOLO en desarrollo y bajo bandera explícita. El guard
// `import.meta.env.DEV` es una constante en el build de producción, así que el
// import dinámico y sus fixtures se eliminan por dead-code elimination: no hay
// datos fijos en el bundle de prod (F8 T03).
if (import.meta.env.DEV && import.meta.env.VITE_P3_MOCK === '1') {
  const { installP3Mock } = await import('./lib/mock/backend');
  installP3Mock();
  console.info('[P3] mock backend activo (VITE_P3_MOCK=1)');
}

const container = document.getElementById('root');
if (!container) throw new Error('Falta el nodo #root en index.html');

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
