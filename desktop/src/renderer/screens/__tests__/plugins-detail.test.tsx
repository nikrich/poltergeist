import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PluginsScreen } from '../plugins';
import type { MarketplaceListing, PluginRecord } from '../../../shared/plugin-types';

const records: PluginRecord[] = [
  {
    id: 'seance',
    dir: '/x/seance',
    manifest: {
      id: 'seance',
      name: 'Séance',
      version: '0.2.0',
      apiVersion: 1,
      icon: 'sparkles',
      entry: { main: 'dist/main.cjs', renderer: 'dist/renderer.mjs' },
    },
    state: 'enabled',
  },
];

const listings: MarketplaceListing[] = [
  {
    id: 'weather',
    name: 'Weather',
    version: '1.0.0',
    description: 'Shows the local forecast.',
    icon: 'cloud',
    author: 'nikrich',
    tags: ['utility', 'forecast'],
    repo: 'https://github.com/nikrich/weather-plugin',
    installed: false,
    installedVersion: null,
    updateAvailable: false,
  },
  {
    id: 'seance',
    name: 'Séance',
    version: '0.2.0',
    description: 'Multi-agent orchestration.',
    icon: 'sparkles',
    author: 'nikrich',
    tags: ['agents'],
    repo: 'https://github.com/nikrich/seance',
    installed: true,
    installedVersion: '0.1.0',
    updateAvailable: true,
  },
];

function openCard(name: string) {
  const card = screen.getByText(name).closest('[role="button"]');
  if (!card) throw new Error(`no clickable card found for ${name}`);
  return userEvent.click(card as HTMLElement);
}

beforeEach(() => {
  window.gb.plugins.list = vi.fn(async () => records.map((r) => ({ ...r })));
  window.gb.plugins.marketplace.list = vi.fn(async () => listings.map((l) => ({ ...l })));
  window.gb.plugins.marketplace.install = vi.fn(async () => ({ ok: true as const }));
  window.gb.plugins.marketplace.update = vi.fn(async () => ({ ok: true as const }));
  window.gb.plugins.uninstall = vi.fn(async () => ({ ok: true as const }));
  window.gb.plugins.setEnabled = vi.fn(async () => ({ ok: true as const }));
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

describe('PluginsScreen detail view', () => {
  it('clicking a marketplace plugin card opens a detail view with full metadata', async () => {
    render(<PluginsScreen />);
    await screen.findByText('Weather');
    await openCard('Weather');

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Shows the local forecast.')).toBeInTheDocument();
    expect(within(dialog).getByText('nikrich')).toBeInTheDocument();
    expect(within(dialog).getByText('utility')).toBeInTheDocument();
    expect(within(dialog).getByText('forecast')).toBeInTheDocument();
    expect(within(dialog).getByText(/github\.com\/nikrich\/weather-plugin/)).toBeInTheDocument();
  });

  it("an installed plugin's detail view shows its installed version and exposes uninstall/enable-disable", async () => {
    render(<PluginsScreen />);
    const installedGrid = await screen.findByTestId('installed-grid');
    await userEvent.click(within(installedGrid).getByText('Séance').closest('[role="button"]') as HTMLElement);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/0\.1\.0/)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /uninstall/i })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /^enable$|^disable$/i })).toBeInTheDocument();
  });

  it('invoking install from the detail view calls marketplace.install with the plugin id', async () => {
    render(<PluginsScreen />);
    await screen.findByText('Weather');
    await openCard('Weather');

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: /install/i }));
    await waitFor(() => expect(window.gb.plugins.marketplace.install).toHaveBeenCalledWith('weather'));
  });

  it('invoking update from the detail view calls marketplace.update with the plugin id', async () => {
    render(<PluginsScreen />);
    const installedGrid = await screen.findByTestId('installed-grid');
    await userEvent.click(within(installedGrid).getByText('Séance').closest('[role="button"]') as HTMLElement);

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: /update/i }));
    await waitFor(() => expect(window.gb.plugins.marketplace.update).toHaveBeenCalledWith('seance'));
  });

  it('invoking uninstall from the detail view calls plugins.uninstall with the plugin id', async () => {
    render(<PluginsScreen />);
    const installedGrid = await screen.findByTestId('installed-grid');
    await userEvent.click(within(installedGrid).getByText('Séance').closest('[role="button"]') as HTMLElement);

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: /uninstall/i }));
    await waitFor(() => expect(window.gb.plugins.uninstall).toHaveBeenCalledWith('seance'));
  });

  it('shows trust messaging in the detail view when install/update can be initiated', async () => {
    render(<PluginsScreen />);
    await screen.findByText('Weather');
    await openCard('Weather');

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/install only code you trust/i)).toBeInTheDocument();
  });

  it('is closed by default, leaving marketplace list action buttons unambiguous', () => {
    render(<PluginsScreen />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
