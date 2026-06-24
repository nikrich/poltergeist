// desktop/src/renderer/components/WebcamCaptureModal.tsx
import { useEffect, useRef, useState } from 'react';
import { Btn } from './Btn';
import { Lucide } from './Lucide';

interface Props {
  open: boolean;
  onClose: () => void;
  onCapture: (file: File) => void;
}

type Phase = 'live' | 'review';

export function WebcamCaptureModal({ open, onClose, onCapture }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [phase, setPhase] = useState<Phase>('live');
  const [error, setError] = useState<string | null>(null);

  function stopStream() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }

  async function startStream() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play?.()?.catch(() => {});
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'camera unavailable');
    }
  }

  useEffect(() => {
    if (!open) return;
    setPhase('live');
    void startStream();
    return () => stopStream();
  }, [open]); // startStream/stopStream are stable inner functions; open is the only reactive dep

  function handleClose() {
    stopStream();
    onClose();
  }

  function shoot() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    const w = video.videoWidth || 1280;
    const h = video.videoHeight || 720;
    canvas.width = w;
    canvas.height = h;
    canvas.getContext('2d')?.drawImage(video, 0, 0, w, h);
    stopStream(); // freeze: no need to keep the camera on during review
    setPhase('review');
  }

  function usePhoto() {
    canvasRef.current?.toBlob(
      (blob) => {
        if (!blob) return;
        onCapture(new File([blob], `webcam-${Date.now()}.jpg`, { type: 'image/jpeg' }));
        onClose();
      },
      'image/jpeg',
      0.9,
    );
  }

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-[520px] overflow-hidden rounded-lg border border-hairline-2 bg-vellum shadow-float">
        <div className="flex items-center justify-between border-b border-hairline px-4 py-2">
          <span className="text-13 font-semibold">{phase === 'live' ? 'Take a photo' : 'Use this photo?'}</span>
          <button type="button" aria-label="close" onClick={handleClose} className="text-ink-3 hover:text-ink-1">✕</button>
        </div>
        <div className="relative flex h-[280px] items-center justify-center bg-black">
          {error ? (
            <div className="px-6 text-center text-12 text-oxblood">{error}</div>
          ) : (
            <>
              <video ref={videoRef} className={phase === 'live' ? 'h-full' : 'hidden'} muted playsInline />
              <canvas ref={canvasRef} className={phase === 'review' ? 'h-full' : 'hidden'} />
            </>
          )}
        </div>
        <div className="flex items-center gap-2 border-t border-hairline px-4 py-3">
          {phase === 'live' ? (
            <button
              type="button"
              aria-label="shutter"
              disabled={!!error}
              onClick={shoot}
              className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-neon text-paper disabled:opacity-40"
            >
              <Lucide name="camera" size={18} />
            </button>
          ) : (
            <>
              <Btn variant="ghost" size="sm" onClick={() => { setPhase('live'); void startStream(); }}>↺ retake</Btn>
              <Btn variant="primary" size="sm" className="ml-auto" onClick={usePhoto}>use photo →</Btn>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
