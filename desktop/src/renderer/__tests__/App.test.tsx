import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from '../App';
import { useNavigation } from '../stores/navigation';
import { useSettings } from '../stores/settings';
import { useFocusSurfaces } from '../lib/focus-mode';

function wrap() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useNavigation.setState({ active: 'today' });
});

afterEach(() => {
  useSettings.setState({ focusMode: false });
  useFocusSurfaces.setState({ count: 0 });
});

describe('App', () => {
  it('renders the brand without throwing', async () => {
    wrap();
    expect(await screen.findByText('poltergeist')).toBeInTheDocument();
  });

  it('navigates to the activity screen from the sidebar', async () => {
    wrap();
    fireEvent.click(await screen.findByRole('button', { name: 'activity' }));
    expect(
      await screen.findByRole('heading', { name: 'activity', level: 1 }),
    ).toBeInTheDocument();
  });

  it('focus mode hides the sidebar and status bar only while an editor surface is up', async () => {
    wrap();
    await screen.findByRole('button', { name: 'activity' });
    expect(document.querySelector('.gb-statusbar')).not.toBeNull();

    // Flag on but nothing to edit on screen: chrome stays.
    act(() => useSettings.setState({ focusMode: true }));
    expect(screen.getByRole('button', { name: 'activity' })).toBeInTheDocument();

    let release!: () => void;
    act(() => {
      release = useFocusSurfaces.getState().register();
    });
    expect(screen.queryByRole('button', { name: 'activity' })).toBeNull();
    expect(document.querySelector('.gb-statusbar')).toBeNull();

    act(() => release());
    expect(await screen.findByRole('button', { name: 'activity' })).toBeInTheDocument();
  });
});
