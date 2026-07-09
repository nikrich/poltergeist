import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MarketplaceScreen } from '../marketplace';
import type { PluginRecord, RegistryEntry } from '../../../shared/plugin-types';

const registryEntries: RegistryEntry[] = [
  {
    id: 'seance',
    repo: 'nikrich/seance',
    author: 'nikrich',
    tags: ['productivity'],
    name: 'Séance',
    description: 'summon your notes',
  },
  {
    id: 'weather-widget',
    repo: 'someone/weather-widget',
    author: 'someone',
    tags: ['widgets'],
    name: 'Weather Widget',
    description: 'shows the weather',
  },
];

const installedRecords: PluginRecord[] = [
  {
    id: 'seance',
    dir: '/x/seance',
    manifest: {
      id: 'seance',
      name: 'Séance',
      version: '0.1.0',
      apiVersion: 1,
      entry: { main: 'dist/main.cjs' },
    },
    state: 'enabled',
  },
];

beforeEach(() => {
  window.gb.plugins.marketplaceList = vi.fn(async () => registryEntries.map((e) => ({ ...e })));
  window.gb.plugins.marketplaceSearch = vi.fn(async (query: string) =>
    registryEntries
      .filter((e) => (e.name ?? e.id).toLowerCase().includes(query.toLowerCase()))
      .map((e) => ({ ...e })),
  );
  window.gb.plugins.list = vi.fn(async () => installedRecords.map((r) => ({ ...r })));
  window.gb.plugins.installFromRegistry = vi.fn(async () => ({ ok: true as const }));
  window.gb.plugins.update = vi.fn(async () => ({ ok: true as const }));
  window.gb.plugins.uninstall = vi.fn(async () => ({ ok: true as const }));
  window.confirm = vi.fn(() => true);
});

describe('MarketplaceScreen', () => {
  it('renders registry entries returned by marketplaceList', async () => {
    render(<MarketplaceScreen />);
    expect(await screen.findByText('Séance')).toBeInTheDocument();
    expect(screen.getByText('Weather Widget')).toBeInTheDocument();
    expect(screen.getByText(/summon your notes/)).toBeInTheDocument();
    expect(screen.getByText(/shows the weather/)).toBeInTheDocument();
    expect(screen.getByText('productivity')).toBeInTheDocument();
    expect(screen.getByText('widgets')).toBeInTheDocument();
  });

  it('typing in the search box triggers marketplaceSearch with the typed query', async () => {
    render(<MarketplaceScreen />);
    await screen.findByText('Séance');
    await userEvent.type(screen.getByPlaceholderText(/search/i), 'weather');
    await waitFor(() =>
      expect(window.gb.plugins.marketplaceSearch).toHaveBeenCalledWith('weather'),
    );
    await waitFor(() => expect(screen.queryByText('Séance')).not.toBeInTheDocument());
    expect(screen.getByText('Weather Widget')).toBeInTheDocument();
  });

  it('clicking install on a not-installed entry calls installFromRegistry with its id', async () => {
    render(<MarketplaceScreen />);
    await screen.findByText('Weather Widget');
    await userEvent.click(screen.getByRole('button', { name: /^install$/i }));
    await waitFor(() =>
      expect(window.gb.plugins.installFromRegistry).toHaveBeenCalledWith('weather-widget'),
    );
  });

  it('shows update and delete for an already-installed entry, and wires them up', async () => {
    render(<MarketplaceScreen />);
    await screen.findByText('Séance');

    await userEvent.click(screen.getByRole('button', { name: /^update$/i }));
    await waitFor(() => expect(window.gb.plugins.update).toHaveBeenCalledWith('seance'));

    await userEvent.click(screen.getByRole('button', { name: /uninstall/i }));
    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => expect(window.gb.plugins.uninstall).toHaveBeenCalledWith('seance'));
  });
});
