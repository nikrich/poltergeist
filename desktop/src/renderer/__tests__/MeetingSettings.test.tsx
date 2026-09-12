import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { MeetingSettings } from '../screens/settings';
import type { SchedulerDiagnostics } from '../lib/api/hooks';
import type { CaptureHelperDiagnostics, RecorderSettings } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ...actual, get: vi.fn(), post: vi.fn() };
});

const HELPER: CaptureHelperDiagnostics = {
  found: true,
  path: '/Applications/Poltergeist.app/Contents/Resources/bin/ghostbrain-capture',
  ok: true,
  code: 0,
  reason: 'ok',
  macos_version: '15.5',
  macos_supported: true,
  screen_recording: 'granted',
  microphone: 'granted',
};

const DIAGNOSTICS: SchedulerDiagnostics = {
  enabled: false,
  active_launchd_plists: [],
  double_scheduling: false,
  ffmpeg_available: false,
  platform: 'darwin',
  effective_backend: 'native',
  capture_helper: HELPER,
};

const RECORDER: RecorderSettings = {
  enabled: true,
  excluded_titles: [],
  manual_context: '',
  capture_backend: 'auto',
  capture_slides: true,
  slide_fps: 1,
  slide_fallback: 'ask',
  capture_backend_effective: 'native',
};

function renderSection(opts?: {
  recorder?: Partial<RecorderSettings>;
  diagnostics?: Partial<SchedulerDiagnostics>;
}) {
  const recorder = { ...RECORDER, ...opts?.recorder };
  const diagnostics = { ...DIAGNOSTICS, ...opts?.diagnostics };
  vi.mocked(client.get).mockImplementation((path: string) => {
    if (path === '/v1/settings/recorder') return Promise.resolve(recorder as never);
    if (path.startsWith('/v1/scheduler/diagnostics')) return Promise.resolve(diagnostics as never);
    if (path === '/v1/vault/contexts') return Promise.resolve({ contexts: ['work'] } as never);
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
  vi.mocked(client.post).mockImplementation((path: string, body?: unknown) => {
    if (path === '/v1/settings/recorder')
      return Promise.resolve({ ...recorder, ...(body as object) } as never);
    if (path === '/v1/recorder/capture/request-permissions')
      return Promise.resolve(diagnostics.capture_helper as never);
    return Promise.reject(new Error(`unexpected POST ${path}`));
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MeetingSettings />
    </QueryClientProvider>,
  );
}

const originalPlatform = window.gb.platform;

/** The grant/re-check buttons stay disabled until the diagnostics probe loads. */
async function findEnabledButton(name: RegExp): Promise<HTMLButtonElement> {
  const btn = (await screen.findByRole('button', { name })) as HTMLButtonElement;
  await waitFor(() => expect(btn.disabled).toBe(false));
  return btn;
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  (window.gb as { platform: NodeJS.Platform }).platform = originalPlatform;
});

describe('MeetingSettings (darwin)', () => {
  it('posts capture_backend when the segmented control changes', async () => {
    renderSection();
    const btn = await screen.findByRole('button', { name: 'blackhole' });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(vi.mocked(client.post)).toHaveBeenCalledWith('/v1/settings/recorder', {
        capture_backend: 'blackhole',
      }),
    );
  });

  it('shows the effective backend and "next recording" note under capture method', async () => {
    renderSection();
    expect(await screen.findByText(/in use: native/)).toBeInTheDocument();
    expect(screen.getByText(/applies to the next recording/)).toBeInTheDocument();
  });

  it('shows the fallback reason when auto resolved to blackhole', async () => {
    renderSection({
      recorder: { capture_backend_effective: 'blackhole' },
      diagnostics: {
        effective_backend: 'blackhole',
        ffmpeg_available: true,
        capture_helper: {
          ...HELPER,
          ok: false,
          code: 3,
          reason: 'screen recording permission denied',
          screen_recording: 'denied',
        },
      },
    });
    expect(
      await screen.findByText(/falling back — screen recording permission denied/),
    ).toBeInTheDocument();
    // ffmpeg row moved here and only shown for the blackhole method.
    expect(screen.getByText(/ffmpeg available \(blackhole method\)/)).toBeInTheDocument();
    expect(screen.getByText('yes')).toBeInTheDocument();
  });

  it('renders the native capture diagnostics rows from the fixture', async () => {
    renderSection();
    expect(await screen.findByText(HELPER.path!)).toBeInTheDocument();
    expect(screen.getByText('found')).toBeInTheDocument();
    expect(screen.getByText(/15\.5 · supported/)).toBeInTheDocument();
    expect(screen.getByText('screen recording')).toBeInTheDocument();
    expect(screen.getByText('microphone')).toBeInTheDocument();
    expect(screen.getAllByText('granted')).toHaveLength(2);
    // Effective backend is native → no ffmpeg row.
    expect(screen.queryByText(/ffmpeg available/)).not.toBeInTheDocument();
  });

  it('disables slide capture unless the effective backend is native', async () => {
    renderSection({
      recorder: { capture_backend_effective: 'blackhole', capture_slides: false },
      diagnostics: { effective_backend: 'blackhole' },
    });
    await screen.findByText('slide capture');
    expect(screen.getByText(/requires the native capture method/)).toBeInTheDocument();
    expect(screen.queryByLabelText('slide sampling')).not.toBeInTheDocument();
  });

  it('shows the slide fallback and sampling selects when slides are on', async () => {
    renderSection();
    const fallback = (await screen.findByLabelText(
      'when no meeting window is found',
    )) as HTMLSelectElement;
    fireEvent.change(fallback, { target: { value: 'display' } });
    await waitFor(() =>
      expect(vi.mocked(client.post)).toHaveBeenCalledWith('/v1/settings/recorder', {
        slide_fallback: 'display',
      }),
    );
    const fps = screen.getByLabelText('slide sampling') as HTMLSelectElement;
    fireEvent.change(fps, { target: { value: '2' } });
    await waitFor(() =>
      expect(vi.mocked(client.post)).toHaveBeenCalledWith('/v1/settings/recorder', {
        slide_fps: 2,
      }),
    );
  });

  it('grant access posts request-permissions then opens the Screen Recording pane', async () => {
    const openExternal = vi
      .spyOn(window.gb.shell, 'openExternal')
      .mockResolvedValue({ ok: true });
    renderSection({
      diagnostics: {
        capture_helper: { ...HELPER, ok: false, screen_recording: 'not_determined' },
      },
    });
    fireEvent.click(await findEnabledButton(/grant access/i));
    await waitFor(() =>
      expect(vi.mocked(client.post)).toHaveBeenCalledWith(
        '/v1/recorder/capture/request-permissions',
      ),
    );
    await waitFor(() =>
      expect(openExternal).toHaveBeenCalledWith(
        'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture',
      ),
    );
    expect(openExternal).toHaveBeenCalledTimes(1);
  });

  it('grant access also opens the Microphone pane when the mic is denied', async () => {
    const openExternal = vi
      .spyOn(window.gb.shell, 'openExternal')
      .mockResolvedValue({ ok: true });
    renderSection({
      diagnostics: { capture_helper: { ...HELPER, ok: false, microphone: 'denied' } },
    });
    fireEvent.click(await findEnabledButton(/grant access/i));
    await waitFor(() =>
      expect(openExternal).toHaveBeenCalledWith(
        'x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone',
      ),
    );
    expect(openExternal).toHaveBeenCalledTimes(2);
  });

  it('re-check fetches diagnostics with refresh=1', async () => {
    renderSection();
    fireEvent.click(await screen.findByRole('button', { name: /re-check/i }));
    await waitFor(() =>
      expect(vi.mocked(client.get)).toHaveBeenCalledWith('/v1/scheduler/diagnostics?refresh=1'),
    );
  });
});

describe('MeetingSettings (win32)', () => {
  it('hides the darwin rows and shows a static WASAPI row', async () => {
    (window.gb as { platform: NodeJS.Platform }).platform = 'win32';
    renderSection({
      recorder: { capture_backend_effective: 'wasapi' },
      diagnostics: { platform: 'win32', effective_backend: 'wasapi', capture_helper: null },
    });
    expect(await screen.findByText('WASAPI loopback')).toBeInTheDocument();
    expect(screen.getByText('capture method')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'blackhole' })).not.toBeInTheDocument();
    expect(screen.queryByText('slide capture')).not.toBeInTheDocument();
    expect(screen.queryByText('native capture')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /grant access/i })).not.toBeInTheDocument();
  });
});
