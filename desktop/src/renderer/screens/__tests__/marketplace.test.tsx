import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
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
    tags: ['utility'],
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
    repo: 'https://github.com/nikrich/seance',
    installed: true,
    installedVersion: '0.1.0',
    updateAvailable: true,
  },
];

beforeEach(() => {
  window.gb.plugins.list = vi.fn(async () => []);
  window.gb.plugins.marketplace.list = vi.fn(async () => listings.map((l) => ({ ...l })));
  window.gb.plugins.marketplace.install = vi.fn(async () => ({ ok: true as const }));
  window.gb.plugins.marketplace.update = vi.fn(async () => ({ ok: true as const }));
});

describe('PluginsScreen marketplace', () => {
  it('lists marketplace entries with name and description', async () => {
    render(<PluginsScreen />);
    expect(await screen.findByText('Weather')).toBeInTheDocument();
    expect(screen.getByText('Shows the local forecast.')).toBeInTheDocument();
    expect(screen.getByText('Séance')).toBeInTheDocument();
    expect(screen.getByText('Multi-agent orchestration.')).toBeInTheDocument();
  });

  it('filters listings by search text', async () => {
    render(<PluginsScreen />);
    await screen.findByText('Weather');
    await userEvent.type(screen.getByPlaceholderText(/search plugins/i), 'weather');
    expect(screen.getByText('Weather')).toBeInTheDocument();
    expect(screen.queryByText('Séance')).not.toBeInTheDocument();
  });

  it('clicking install calls marketplace.install with the entry id', async () => {
    render(<PluginsScreen />);
    await screen.findByText('Weather');
    await userEvent.click(screen.getByRole('button', { name: /^install$/i }));
    await waitFor(() =>
      expect(window.gb.plugins.marketplace.install).toHaveBeenCalledWith('weather'),
    );
  });

  it('clicking update calls marketplace.update with the entry id', async () => {
    render(<PluginsScreen />);
    await screen.findByText('Séance');
    expect(screen.getByText(/update available/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^update$/i }));
    await waitFor(() =>
      expect(window.gb.plugins.marketplace.update).toHaveBeenCalledWith('seance'),
    );
  });
});
