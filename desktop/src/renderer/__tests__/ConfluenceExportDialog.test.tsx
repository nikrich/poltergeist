import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Mock the hooks module so we control mutation and query behaviour.
vi.mock('../lib/api/hooks', () => ({
  useImportSpaces: vi.fn(),
  useExportConfluence: vi.fn(),
}));

import { useImportSpaces, useExportConfluence } from '../lib/api/hooks';
import { ConfluenceExportDialog } from '../components/ConfluenceExportDialog';
import type { ImportSpace } from '../../shared/api-types';

const spaces: ImportSpace[] = [
  { site: 'example.atlassian.net', siteSlug: 'example', key: 'ENG', name: 'Engineering', context: 'sanlam' },
  { site: 'example.atlassian.net', siteSlug: 'example', key: 'MKT', name: 'Marketing', context: 'sanlam' },
];

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  window.gb = {
    ...window.gb,
    shell: { openExternal: vi.fn().mockResolvedValue({ ok: true }), openPath: vi.fn() },
  } as typeof window.gb;
});

describe('ConfluenceExportDialog', () => {
  it('renders space options from useImportSpaces', () => {
    vi.mocked(useImportSpaces).mockReturnValue({
      data: spaces,
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useImportSpaces>);

    const mutate = vi.fn();
    vi.mocked(useExportConfluence).mockReturnValue({
      mutate,
      isPending: false,
    } as unknown as ReturnType<typeof useExportConfluence>);

    render(withQuery(
      <ConfluenceExportDialog jotId="jot-1" defaultTitle="my doc" onClose={() => {}} />,
    ));

    expect(screen.getByRole('option', { name: /Engineering/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Marketing/ })).toBeInTheDocument();
  });

  it('calls mutate with chosen space key on export', () => {
    vi.mocked(useImportSpaces).mockReturnValue({
      data: spaces,
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useImportSpaces>);

    const mutate = vi.fn();
    vi.mocked(useExportConfluence).mockReturnValue({
      mutate,
      isPending: false,
    } as unknown as ReturnType<typeof useExportConfluence>);

    render(withQuery(
      <ConfluenceExportDialog jotId="jot-42" defaultTitle="my doc" onClose={() => {}} />,
    ));

    // Switch to the second space
    const select = screen.getByRole('combobox');
    fireEvent.change(select, { target: { value: 'MKT' } });

    fireEvent.click(screen.getByRole('button', { name: /export/ }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({ jot_id: 'jot-42', space_key: 'MKT' }),
      expect.any(Object),
    );
  });

  it('shows export-as-new button when error contains "no longer exists"', async () => {
    vi.mocked(useImportSpaces).mockReturnValue({
      data: spaces,
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useImportSpaces>);

    // Capture the onError callback so we can invoke it.
    let capturedOnError: ((err: Error) => void) | undefined;
    const mutate = vi.fn((_req: unknown, opts: { onError?: (err: Error) => void }) => {
      capturedOnError = opts?.onError;
    });
    vi.mocked(useExportConfluence).mockReturnValue({
      mutate,
      isPending: false,
    } as unknown as ReturnType<typeof useExportConfluence>);

    render(withQuery(
      <ConfluenceExportDialog jotId="jot-del" defaultTitle="gone doc" onClose={() => {}} />,
    ));

    // Trigger initial export
    fireEvent.click(screen.getByRole('button', { name: /export/ }));
    expect(mutate).toHaveBeenCalledTimes(1);

    // Simulate the "no longer exists" error response
    capturedOnError!(new Error('linked page no longer exists on confluence'));

    await waitFor(() =>
      expect(screen.getByText(/page was deleted on confluence/i)).toBeInTheDocument(),
    );

    // The "export as new" button should be visible
    const retryBtn = screen.getByRole('button', { name: /export as new/i });
    expect(retryBtn).toBeInTheDocument();

    // Clicking it should call mutate again with force_new: true
    fireEvent.click(retryBtn);
    expect(mutate).toHaveBeenCalledTimes(2);
    expect(mutate).toHaveBeenLastCalledWith(
      expect.objectContaining({ force_new: true }),
      expect.any(Object),
    );
  });
});
