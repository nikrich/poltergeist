import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PluginsScreen } from '../plugins';
import type { MarketplaceListing } from '../../../shared/plugin-types';

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
    tags: ['productivity'],
    repo: 'https://github.com/nikrich/seance',
    installed: true,
    installedVersion: '0.1.0',
    updateAvailable: true,
  },
  {
    id: 'ghostwriter',
    name: 'Ghostwriter',
    version: '0.1.0',
    description: 'Drafts copy for you.',
    icon: 'pen',
    tags: ['productivity', 'writing'],
    repo: 'https://github.com/nikrich/ghostwriter',
    installed: false,
    installedVersion: null,
    updateAvailable: false,
  },
];

beforeEach(() => {
  window.gb.plugins.list = vi.fn(async () => []);
  window.gb.plugins.marketplace.list = vi.fn(async () => listings.map((l) => ({ ...l })));
  window.gb.plugins.marketplace.install = vi.fn(async () => ({ ok: true as const }));
  window.gb.plugins.marketplace.update = vi.fn(async () => ({ ok: true as const }));
});

describe('PluginsScreen tag filter', () => {
  it('renders a filter chip for each distinct tag across listings', async () => {
    render(<PluginsScreen />);
    await screen.findByText('Weather');

    expect(screen.getByRole('button', { name: 'utility' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'forecast' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'productivity' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'writing' })).toBeInTheDocument();
  });

  it('narrows the Discover grid to plugins carrying the selected tag', async () => {
    render(<PluginsScreen />);
    await screen.findByText('Weather');

    await userEvent.click(screen.getByRole('button', { name: 'productivity' }));

    expect(screen.getByText('Séance')).toBeInTheDocument();
    expect(screen.getByText('Ghostwriter')).toBeInTheDocument();
    expect(screen.queryByText('Weather')).not.toBeInTheDocument();
  });

  it('restores the full set when the active tag is cleared', async () => {
    render(<PluginsScreen />);
    await screen.findByText('Weather');

    const productivityChip = screen.getByRole('button', { name: 'productivity' });
    await userEvent.click(productivityChip);
    expect(screen.queryByText('Weather')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'all' }));

    expect(screen.getByText('Weather')).toBeInTheDocument();
    expect(screen.getByText('Séance')).toBeInTheDocument();
    expect(screen.getByText('Ghostwriter')).toBeInTheDocument();
  });

  it('composes the tag filter with search text as an intersection', async () => {
    render(<PluginsScreen />);
    await screen.findByText('Weather');

    await userEvent.click(screen.getByRole('button', { name: 'productivity' }));
    expect(screen.getByText('Séance')).toBeInTheDocument();
    expect(screen.getByText('Ghostwriter')).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText(/search plugins/i), 'ghost');

    expect(screen.getByText('Ghostwriter')).toBeInTheDocument();
    expect(screen.queryByText('Séance')).not.toBeInTheDocument();
    expect(screen.queryByText('Weather')).not.toBeInTheDocument();
  });
});
