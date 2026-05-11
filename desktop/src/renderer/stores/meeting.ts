import { useCallback, useMemo } from 'react';
import {
  useClearRecording,
  useRecorderStatus,
  useStartRecording,
  useStopRecording,
} from '../lib/api/hooks';
import type { RecorderStatus, StartRecordingRequest } from '../../shared/api-types';

export type MeetingPhase = 'pre' | 'recording' | 'transcribing' | 'post';

interface MeetingState {
  phase: MeetingPhase;
  startedAt: number | null;
  title: string | null;
  transcriptPath: string | null;
  error: string | null;
  owner: RecorderStatus['owner'];
  isLoading: boolean;
  start: (opts?: StartRecordingRequest) => Promise<void>;
  stop: () => Promise<void>;
  reset: () => Promise<void>;
}

function phaseFromStatus(status: RecorderStatus | undefined): MeetingPhase {
  if (!status) return 'pre';
  switch (status.phase) {
    case 'recording':
      return 'recording';
    case 'transcribing':
      return 'transcribing';
    case 'done':
      return 'post';
    default:
      return 'pre';
  }
}

function startedAtMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

/** Recorder state for the meetings UI, sourced from the sidecar.
 *
 * Polls /v1/recorder/status while a recording is active or transcribing so
 * the UI transitions to the post-meeting view as soon as whisper finishes.
 */
export function useMeeting(): MeetingState {
  const statusQuery = useRecorderStatus();
  const startMutation = useStartRecording();
  const stopMutation = useStopRecording();
  const clearMutation = useClearRecording();

  const refetchStatus = statusQuery.refetch;
  const status = statusQuery.data;

  const phase = phaseFromStatus(status);

  const start = useCallback(
    async (opts?: StartRecordingRequest) => {
      await startMutation.mutateAsync(opts ?? {});
      await refetchStatus();
    },
    [startMutation, refetchStatus],
  );

  const stop = useCallback(async () => {
    await stopMutation.mutateAsync();
    await refetchStatus();
  }, [stopMutation, refetchStatus]);

  const reset = useCallback(async () => {
    if (phase === 'post') {
      await clearMutation.mutateAsync();
      await refetchStatus();
    }
  }, [clearMutation, refetchStatus, phase]);

  return useMemo(
    () => ({
      phase,
      startedAt: startedAtMs(status?.startedAt ?? null),
      title: status?.title ?? null,
      transcriptPath: status?.transcriptPath ?? null,
      error: status?.error ?? null,
      owner: status?.owner ?? null,
      isLoading: statusQuery.isLoading,
      start,
      stop,
      reset,
    }),
    [phase, status, statusQuery.isLoading, start, stop, reset],
  );
}
