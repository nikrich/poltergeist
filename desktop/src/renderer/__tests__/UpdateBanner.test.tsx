import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { UpdateBanner } from '../components/UpdateBanner';

type Listener<T> = (payload: T) => void;

function makeUpdatesStub() {
  let availableCb: Listener<{ version: string; canSelfUpdate: boolean }> | null = null;
  let progressCb: Listener<{ percent: number }> | null = null;
  let downloadedCb: Listener<{ version: string }> | null = null;

  const download = vi.fn().mockResolvedValue({ ok: true });
  const install = vi.fn().mockResolvedValue(undefined);

  return {
    stub: {
      download,
      install,
      onAvailable: (cb: Listener<{ version: string; canSelfUpdate: boolean }>) => {
        availableCb = cb;
        return () => {
          availableCb = null;
        };
      },
      onProgress: (cb: Listener<{ percent: number }>) => {
        progressCb = cb;
        return () => {
          progressCb = null;
        };
      },
      onDownloaded: (cb: Listener<{ version: string }>) => {
        downloadedCb = cb;
        return () => {
          downloadedCb = null;
        };
      },
    },
    fireAvailable: (p: { version: string; canSelfUpdate: boolean }) => act(() => { availableCb?.(p); }),
    fireProgress: (p: { percent: number }) => act(() => { progressCb?.(p); }),
    fireDownloaded: (p: { version: string }) => act(() => { downloadedCb?.(p); }),
    download,
    install,
  };
}

beforeEach(() => {
  window.gb = {
    ...window.gb,
    updates: makeUpdatesStub().stub,
  } as typeof window.gb;
});

describe('UpdateBanner', () => {
  it('is hidden by default', () => {
    render(<UpdateBanner />);
    expect(screen.queryByText(/is available/)).not.toBeInTheDocument();
  });

  it('shows the available state with version and an Update button', () => {
    const updates = makeUpdatesStub();
    window.gb = { ...window.gb, updates: updates.stub } as typeof window.gb;

    render(<UpdateBanner />);
    updates.fireAvailable({ version: '1.2.3', canSelfUpdate: true });

    expect(screen.getByText(/Poltergeist v1.2.3 is available/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Update' })).toBeInTheDocument();
  });

  it('clicking Update calls download() and shows progress', async () => {
    const updates = makeUpdatesStub();
    window.gb = { ...window.gb, updates: updates.stub } as typeof window.gb;

    render(<UpdateBanner />);
    updates.fireAvailable({ version: '1.2.3', canSelfUpdate: true });
    fireEvent.click(screen.getByRole('button', { name: 'Update' }));

    expect(updates.download).toHaveBeenCalled();
    updates.fireProgress({ percent: 42 });

    expect(await screen.findByText(/42/)).toBeInTheDocument();
  });

  it('shows Restart to update in the downloaded state and clicking calls install()', async () => {
    const updates = makeUpdatesStub();
    window.gb = { ...window.gb, updates: updates.stub } as typeof window.gb;

    render(<UpdateBanner />);
    updates.fireAvailable({ version: '1.2.3', canSelfUpdate: true });
    fireEvent.click(screen.getByRole('button', { name: 'Update' }));
    updates.fireDownloaded({ version: '1.2.3' });

    const restartBtn = await screen.findByRole('button', { name: 'Restart to update' });
    fireEvent.click(restartBtn);
    expect(updates.install).toHaveBeenCalled();
  });

  it('dismiss hides the banner', async () => {
    const updates = makeUpdatesStub();
    window.gb = { ...window.gb, updates: updates.stub } as typeof window.gb;

    render(<UpdateBanner />);
    updates.fireAvailable({ version: '1.2.3', canSelfUpdate: true });
    expect(await screen.findByText(/is available/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'dismiss' }));
    expect(screen.queryByText(/is available/)).not.toBeInTheDocument();
  });

  it('a failed download returns to the available state silently', async () => {
    const updates = makeUpdatesStub();
    updates.download.mockResolvedValue({ ok: false, error: 'network error' });
    window.gb = { ...window.gb, updates: updates.stub } as typeof window.gb;

    render(<UpdateBanner />);
    updates.fireAvailable({ version: '1.2.3', canSelfUpdate: true });
    fireEvent.click(screen.getByRole('button', { name: 'Update' }));
    await act(async () => {});

    expect(screen.getByRole('button', { name: 'Update' })).toBeInTheDocument();
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
  });

  it('canSelfUpdate: false routes the button to shell.openExternal with the releases URL', () => {
    const updates = makeUpdatesStub();
    const openExternal = vi.fn().mockResolvedValue({ ok: true });
    window.gb = {
      ...window.gb,
      updates: updates.stub,
      shell: { ...window.gb.shell, openExternal },
    } as typeof window.gb;

    render(<UpdateBanner />);
    updates.fireAvailable({ version: '1.2.3', canSelfUpdate: false });

    fireEvent.click(screen.getByRole('button', { name: 'Update' }));

    expect(openExternal).toHaveBeenCalledWith('https://github.com/nikrich/poltergeist/releases');
    expect(updates.download).not.toHaveBeenCalled();
  });
});
