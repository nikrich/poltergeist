// desktop/src/renderer/__tests__/WebcamCaptureModal.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { WebcamCaptureModal } from '../components/WebcamCaptureModal';

const stop = vi.fn();
beforeEach(() => {
  stop.mockClear();
  const track = { stop, kind: 'video' };
  const stream = { getTracks: () => [track] } as unknown as MediaStream;
  (navigator as unknown as { mediaDevices: MediaDevices }).mediaDevices = {
    getUserMedia: vi.fn(async () => stream),
    enumerateDevices: vi.fn(async () => [
      { kind: 'videoinput', deviceId: 'cam1', label: 'FaceTime HD' },
    ]),
  } as unknown as MediaDevices;
  // jsdom does not implement HTMLMediaElement.prototype.play — stub narrowly.
  HTMLMediaElement.prototype.play = vi.fn(async () => {});
  // jsdom has no canvas encoder; stub getContext + toBlob.
  HTMLCanvasElement.prototype.getContext = vi.fn(
    () => ({ drawImage: vi.fn() }),
  ) as unknown as typeof HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.toBlob = function (cb: BlobCallback) {
    cb(new Blob([new Uint8Array([1])], { type: 'image/jpeg' }));
  };
});

describe('WebcamCaptureModal', () => {
  it('stops camera tracks when closed', async () => {
    const onClose = vi.fn();
    render(<WebcamCaptureModal open onClose={onClose} onCapture={() => {}} />);
    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: /close|cancel|✕/i }));
    expect(stop).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('emits a jpeg File on capture → use photo', async () => {
    const onCapture = vi.fn();
    render(<WebcamCaptureModal open onClose={() => {}} onCapture={onCapture} />);
    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: /shutter|capture/i }));
    fireEvent.click(await screen.findByRole('button', { name: /use photo/i }));
    await waitFor(() => expect(onCapture).toHaveBeenCalled());
    const captured = onCapture.mock.calls[0]![0] as File;
    expect(captured).toBeInstanceOf(File);
    expect(captured.type).toBe('image/jpeg');
  });
});
