import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from '../App';
import { useNavigation } from '../stores/navigation';

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
});
