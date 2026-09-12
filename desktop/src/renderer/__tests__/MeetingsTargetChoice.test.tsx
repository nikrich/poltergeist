import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { ActiveRecording, MeetingsScreen } from '../screens/meetings';
import type { RecorderStatus } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ...actual, get: vi.fn(), post: vi.fn() };
});

const RECORDING: RecorderStatus = {
  phase: 'recording',
  owner: 'manual',
  title: 'Design review',
  startedAt: new Date(Date.now() - 60_000).toISOString(),
  wavPath: '/tmp/x.wav',
  transcriptPath: null,
  error: null,
  awaitingTargetChoice: true,
  captureBackend: 'native',
  captureWindows: [
    { windowId: 101, app: 'com.microsoft.teams2', appName: 'Microsoft Teams', title: 'Design review | Teams', width: 1440, height: 900, candidate: false },
    { windowId: 202, app: 'com.google.Chrome', appName: 'Google Chrome', title: 'Q3 roadmap - Google Slides', width: 1280, height: 800, candidate: false },
    { windowId: 303, app: 'com.apple.finder', appName: 'Finder', title: 'Downloads', width: 800, height: 600, candidate: false },
  ],
};

function mockApi(status: RecorderStatus) {
  vi.mocked(client.get).mockImplementation((path: string) => {
    if (path === '/v1/recorder/status') return Promise.resolve(status as never);
    if (path === '/v1/agenda') return Promise.resolve([] as never);
    if (path.startsWith('/v1/meetings')) return Promise.resolve({ total: 0, items: [] } as never);
    if (path === '/v1/settings/recorder')
      return Promise.resolve({
        enabled: true,
        excluded_titles: [],
        manual_context: '',
        capture_backend: 'auto',
        capture_slides: true,
        slide_fps: 1,
        slide_fallback: 'ask',
        capture_backend_effective: 'native',
      } as never);
    if (path.startsWith('/v1/scheduler/diagnostics'))
      return Promise.resolve({
        enabled: false,
        active_launchd_plists: [],
        double_scheduling: false,
        ffmpeg_available: false,
        platform: 'darwin',
        effective_backend: 'native',
        capture_helper: null,
      } as never);
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
  vi.mocked(client.post).mockImplementation((path: string) => {
    if (path === '/v1/recorder/capture/target')
      return Promise.resolve({ ...status, awaitingTargetChoice: false, captureWindows: [] } as never);
    return Promise.reject(new Error(`unexpected POST ${path}`));
  });
}

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

beforeEach(() => vi.clearAllMocks());

describe('meetings › no-meeting-window prompt', () => {
  it('renders the prompt card while status reports awaitingTargetChoice and notifies main', async () => {
    mockApi(RECORDING);
    const notify = vi.spyOn(window.gb.recorder, 'notifyTargetChoice').mockResolvedValue({ ok: true });
    render(wrap(<MeetingsScreen />));
    expect(
      await screen.findByText('No meeting window found. Capture your screen for slides?'),
    ).toBeInTheDocument();
    expect(screen.getByText('System audio (ScreenCaptureKit)')).toBeInTheDocument();
    expect(screen.getByText('Slides (screen key-frames)')).toBeInTheDocument();
    await waitFor(() => expect(notify).toHaveBeenCalledTimes(1));
  });

  it('does not render the card when awaitingTargetChoice is false', async () => {
    mockApi({ ...RECORDING, awaitingTargetChoice: false });
    render(wrap(<MeetingsScreen />));
    await screen.findByText('Design review');
    expect(screen.queryByText(/No meeting window found/)).not.toBeInTheDocument();
  });

  it('clicking "Entire screen" posts {choice: "display"} and hides the card', async () => {
    mockApi(RECORDING);
    render(wrap(<MeetingsScreen />));
    fireEvent.click(await screen.findByRole('button', { name: 'Entire screen' }));
    await waitFor(() =>
      expect(vi.mocked(client.post)).toHaveBeenCalledWith('/v1/recorder/capture/target', {
        choice: 'display',
      }),
    );
    await waitFor(() =>
      expect(screen.queryByText(/No meeting window found/)).not.toBeInTheDocument(),
    );
  });

  it('clicking "Audio only" posts {choice: "audio"}', async () => {
    mockApi(RECORDING);
    render(wrap(<ActiveRecording startedAt={Date.now()} title="t" onStop={() => {}} awaitingTargetChoice />));
    fireEvent.click(await screen.findByRole('button', { name: 'Audio only' }));
    await waitFor(() =>
      expect(vi.mocked(client.post)).toHaveBeenCalledWith('/v1/recorder/capture/target', {
        choice: 'audio',
      }),
    );
  });

  it('lists the windows from captureWindows in order with app, title and size', async () => {
    mockApi(RECORDING);
    render(wrap(<MeetingsScreen />));
    const list = await screen.findByRole('list', { name: 'windows' });
    const rows = within(list).getAllByRole('button');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('Microsoft Teams');
    expect(rows[0]).toHaveTextContent('Design review | Teams');
    expect(rows[0]).toHaveTextContent('1440×900');
    expect(rows[2]).toHaveTextContent('Finder');
    expect(screen.queryByText(/no windows detected yet/)).not.toBeInTheDocument();
  });

  it('clicking a window row posts {choice: "window", window_id}', async () => {
    mockApi(RECORDING);
    render(wrap(<MeetingsScreen />));
    const list = await screen.findByRole('list', { name: 'windows' });
    fireEvent.click(within(list).getByText('Q3 roadmap - Google Slides'));
    await waitFor(() =>
      expect(vi.mocked(client.post)).toHaveBeenCalledWith('/v1/recorder/capture/target', {
        choice: 'window',
        window_id: 202,
      }),
    );
  });

  it('shows a placeholder when no windows were reported', async () => {
    mockApi({ ...RECORDING, captureWindows: [] });
    render(wrap(<MeetingsScreen />));
    expect(await screen.findByText('no windows detected yet…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Entire screen' })).toBeInTheDocument();
  });

  it('labels system audio as BlackHole when the recording uses that backend', async () => {
    mockApi({ ...RECORDING, awaitingTargetChoice: false, captureBackend: 'blackhole' });
    render(wrap(<MeetingsScreen />));
    expect(await screen.findByText('System audio (BlackHole)')).toBeInTheDocument();
  });
});
