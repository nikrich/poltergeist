import { useCallback, useEffect, useMemo, useRef } from 'react';
import {
  useClearRecording,
  useRecorderStatus,
  useStartRecording,
  useStopRecording,
} from '../lib/api/hooks';
import type { CaptureWindow, RecorderStatus, StartRecordingRequest } from '../../shared/api-types';

export type MeetingPhase = 'pre' | 'recording' | 'transcribing' | 'post';

interface MeetingState {
  phase: MeetingPhase;
  startedAt: number | null;
  title: string | null;
  transcriptPath: string | null;
  error: string | null;
  owner: RecorderStatus['owner'];
  /** Native capture found no meeting window and wants a display/audio choice. */
  awaitingTargetChoice: boolean;
  /** Backend used by the active/last recording, if the sidecar reported one. */
  captureBackend: string | null;
  /** Windows available for slide sampling while awaitingTargetChoice; refreshed by the status poll. */
  captureWindows: CaptureWindow[];
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
  // Optional-chain on the flag so an older sidecar without the field still works.
  const awaitingTargetChoice = phase === 'recording' && status?.awaitingTargetChoice === true;
  const captureWindows = useMemo<CaptureWindow[]>(
    () => (awaitingTargetChoice ? status?.captureWindows ?? [] : []),
    [awaitingTargetChoice, status?.captureWindows],
  );

  // Surface the "no meeting window" prompt as an OS notification once per
  // transition so a hidden/minimised window still gets the user's attention.
  // The renderer already polls status while recording, so main doesn't need
  // its own poll — it just raises the notification on request.
  const notifiedRef = useRef(false);
  useEffect(() => {
    if (awaitingTargetChoice && !notifiedRef.current) {
      notifiedRef.current = true;
      void window.gb.recorder.notifyTargetChoice();
    } else if (!awaitingTargetChoice) {
      notifiedRef.current = false;
    }
  }, [awaitingTargetChoice]);

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
      awaitingTargetChoice,
      captureBackend: status?.captureBackend ?? null,
      captureWindows,
      isLoading: statusQuery.isLoading,
      start,
      stop,
      reset,
    }),
    [phase, status, awaitingTargetChoice, captureWindows, statusQuery.isLoading, start, stop, reset],
  );
}
