import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import Inference from '../src/pages/Inference';

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
});

function pngFile(name = 'foto.png'): File {
  return new File([new Uint8Array([137, 80, 78, 71])], name, { type: 'image/png' });
}

describe('Página Inference', () => {
  it('predice con la versión activa y muestra clase, probabilidades y versión', async () => {
    const user = userEvent.setup();
    render(<Inference />);

    await user.upload(screen.getByLabelText(/imagen/i), pngFile());
    await user.click(screen.getByRole('button', { name: /predecir/i }));

    expect(await screen.findByText(/clase predicha/i)).toBeInTheDocument();
    // Versión de modelo activa usada (1.0.0 en el mock).
    expect(await screen.findByText(/1\.0\.0/)).toBeInTheDocument();
  });

  it('rechaza en cliente un archivo que no es imagen', async () => {
    const user = userEvent.setup();
    render(<Inference />);

    await user.upload(
      screen.getByLabelText(/imagen/i),
      new File(['no soy imagen'], 'a.txt', { type: 'text/plain' }),
    );

    expect(await screen.findByText(/JPEG/i)).toBeInTheDocument();
  });

  it('envía la predicción a la cola de anotación', async () => {
    const user = userEvent.setup();
    render(<Inference />);

    await user.upload(screen.getByLabelText(/imagen/i), pngFile());
    await user.click(screen.getByRole('button', { name: /predecir/i }));
    await screen.findByText(/clase predicha/i);

    await user.click(await screen.findByRole('button', { name: /anotaci/i }));
    expect(await screen.findByText(/77/)).toBeInTheDocument();
  });
});
