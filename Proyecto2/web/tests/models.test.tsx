import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { installP3Mock, uninstallP3Mock } from '../src/lib/mock/backend';
import Models from '../src/pages/Models';

beforeEach(() => {
  installP3Mock();
});

afterEach(() => {
  uninstallP3Mock();
});

describe('Página Models', () => {
  it('lista las versiones publicadas y marca la activa', async () => {
    render(<Models />);
    expect(await screen.findByText('1.0.0')).toBeInTheDocument();
    expect(await screen.findByText('0.9.0')).toBeInTheDocument();
    expect(await screen.findByText(/versión activa:\s*1\.0\.0/i)).toBeInTheDocument();
  });

  it('activar otra versión cambia la versión activa', async () => {
    const user = userEvent.setup();
    render(<Models />);
    await user.click(await screen.findByRole('button', { name: /usar 0\.9\.0/i }));
    expect(await screen.findByText(/versión activa:\s*0\.9\.0/i)).toBeInTheDocument();
  });

  it('no deja activar una versión cuyo objeto no existe (409)', async () => {
    const user = userEvent.setup();
    render(<Models />);
    await user.click(await screen.findByRole('button', { name: /usar 0\.8\.0/i }));
    expect(await screen.findByText(/no existe/i)).toBeInTheDocument();
    // La activa no cambió.
    expect(await screen.findByText(/versión activa:\s*1\.0\.0/i)).toBeInTheDocument();
  });
});
