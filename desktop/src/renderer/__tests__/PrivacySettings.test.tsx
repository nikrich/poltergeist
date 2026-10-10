import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PrivacySettings } from '../screens/settings';
import { useSettings } from '../stores/settings';

beforeEach(() => {
  useSettings.setState({ loadRemoteImages: false });
});

afterEach(() => {
  vi.restoreAllMocks();
});

const toggle = () => screen.getByRole('button', { name: 'load remote images' });

describe('PrivacySettings — load remote images', () => {
  it('is off by default and says it takes effect immediately', () => {
    render(<PrivacySettings />);
    expect(toggle()).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByText(/takes effect immediately/i)).toBeInTheDocument();
  });

  it('turning it on saves the setting', async () => {
    const set = vi.spyOn(window.gb.settings, 'set');
    render(<PrivacySettings />);
    fireEvent.click(toggle());
    await waitFor(() => expect(useSettings.getState().loadRemoteImages).toBe(true));
    expect(set).toHaveBeenCalledWith('loadRemoteImages', true);
  });
});
