// Extiende `expect` con los matchers de jest-dom (toBeInTheDocument, etc.) y
// desmonta el árbol de React entre pruebas para que no se filtre estado.
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
});
