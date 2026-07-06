import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PluginsScreen } from '../plugins';
import type { PluginRecord } from '../../../shared/plugin-types';

const records: PluginRecord[] = [
  {
    id: 'seance',
    dir: '/x/seance',
    manifest: {
      id: 'seance',
      name: 'Séance',
      version: '0.1.0',
      apiVersion: 1,
      icon: 'sparkles',
      entry: { main: 'dist/main.cjs', renderer: 'dist/renderer.mjs' },
    },
    state: 'enabled',
  },
  {
    id: 'broken',
    dir: '/x/broken',
    manifest: {
      id: 'broken',
      name: 'Broken',
      version: '1.0.0',
      apiVersion: 1,
      entry: { main: 'dist/main.cjs' },
    },
    state: 'errored',
    error: 'boom',
  },
];

beforeEach(() => {
  window.gb.plugins.list = vi.fn(async () => records.map((r) => ({ ...r })));
  window.gb.plugins.setEnabled = vi.fn(async () => ({ ok: true as const }));
  window.gb.plugins.installFromGit = vi.fn(async () => ({ ok: true as const }));
});

describe('PluginsScreen', () => {
  it('lists installed plugins with state and errors', async () => {
    render(<PluginsScreen />);
    expect(await screen.findByText('Séance')).toBeInTheDocument();
    expect(screen.getByText('Broken')).toBeInTheDocument();
    expect(screen.getByText(/boom/)).toBeInTheDocument();
    expect(screen.getByText('errored')).toBeInTheDocument();
  });

  it('toggling calls setEnabled with the flipped value', async () => {
    render(<PluginsScreen />);
    await screen.findByText('Séance');
    const toggles = screen.getAllByRole('button', { pressed: true });
    await userEvent.click(toggles[0]!);
    await waitFor(() =>
      expect(window.gb.plugins.setEnabled).toHaveBeenCalledWith('seance', false),
    );
  });

  it('git install sends url and subdir', async () => {
    render(<PluginsScreen />);
    await screen.findByText('Séance');
    await userEvent.type(screen.getByPlaceholderText(/https:\/\/github.com/i), 'https://github.com/nikrich/seance');
    await userEvent.type(screen.getByPlaceholderText(/subdirectory/i), 'poltergeist-plugin');
    await userEvent.click(screen.getByRole('button', { name: /install from git/i }));
    await waitFor(() =>
      expect(window.gb.plugins.installFromGit).toHaveBeenCalledWith(
        'https://github.com/nikrich/seance',
        'poltergeist-plugin',
      ),
    );
  });
});
