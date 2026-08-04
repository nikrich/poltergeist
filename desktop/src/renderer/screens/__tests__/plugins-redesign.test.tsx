import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PluginsScreen } from '../plugins';
import type { MarketplaceListing, PluginRecord } from '../../../shared/plugin-types';

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
];

const listings: MarketplaceListing[] = [
  {
    id: 'weather',
    name: 'Weather',
    version: '1.0.0',
    description: 'Shows the local forecast.',
    icon: 'cloud',
    author: 'nikrich',
    tags: ['utility'],
    repo: 'https://github.com/nikrich/weather-plugin',
    installed: false,
    installedVersion: null,
    updateAvailable: false,
  },
];

beforeEach(() => {
  window.gb.plugins.list = vi.fn(async () => records.map((r) => ({ ...r })));
  window.gb.plugins.marketplace.list = vi.fn(async () => listings.map((l) => ({ ...l })));
});

describe('PluginsScreen redesign', () => {
  it('renders Installed and Discover as distinct, always-queryable sections', async () => {
    render(<PluginsScreen />);
    expect(await screen.findByTestId('installed-section')).toBeInTheDocument();
    expect(screen.getByTestId('discover-section')).toBeInTheDocument();
  });

  it('renders installed plugins as cards inside a grid container', async () => {
    render(<PluginsScreen />);
    const grid = await screen.findByTestId('installed-grid');
    expect(grid).toHaveTextContent('Séance');
  });

  it('renders marketplace entries as cards inside a grid container', async () => {
    render(<PluginsScreen />);
    const grid = await screen.findByTestId('discover-grid');
    expect(grid).toHaveTextContent('Weather');
  });

  it('keeps the trust messaging visible near install actions', async () => {
    render(<PluginsScreen />);
    const notices = await screen.findAllByText(/install only code you trust/i);
    expect(notices.length).toBeGreaterThan(0);
  });
});
