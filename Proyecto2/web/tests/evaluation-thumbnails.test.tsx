import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import Evaluation from '../src/pages/Evaluation';

// Criterio 4.4: cada ejemplo lleva su miniatura (<img src=".../evaluation/crops/{crop_id}">),
// los errores se resaltan y, si falta el recorte, se avisa en vez de imagen rota.

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
});

describe('Evaluation — miniaturas (4.4)', () => {
  it('cada ejemplo lleva su miniatura con el src del recorte', async () => {
    render(<Evaluation />);
    const img = await screen.findByAltText(/cat → cat/i); // acierto 0.1.3:a4
    const src = img.getAttribute('src') ?? '';
    expect(src).toContain('/api/p3/evaluation/crops/');
    expect(src).toContain(encodeURIComponent('0.1.3:a4'));
  });

  it('resalta los errores', async () => {
    const { container } = render(<Evaluation />);
    await screen.findByAltText(/person → cat/i); // error 0.1.3:a17
    expect(container.querySelector('.crop-error')).toBeTruthy();
  });

  it('si falta un recorte, muestra un aviso en vez de imagen rota', async () => {
    render(<Evaluation />);
    const imgs = await screen.findAllByRole('img');
    fireEvent.error(imgs[0]!);
    expect(await screen.findByText(/sin recorte/i)).toBeInTheDocument();
  });

  it('muestra la clase más confundida con su conteo (most_confused)', async () => {
    render(<Evaluation />);
    // Lo que daría el backend con esta matriz (errores=1, desempate alfabético): cat → dog.
    expect(
      await screen.findByText(/par más confundido: cat → dog.*1 caso/i),
    ).toBeInTheDocument();
  });
});
