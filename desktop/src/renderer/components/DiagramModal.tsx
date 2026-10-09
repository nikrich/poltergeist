import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { renderMermaid, type MermaidResult } from '../lib/editor/mermaid-render';
import { Lucide } from './Lucide';

interface Props {
  source: string;
  onClose: () => void;
}

const BUTTON_ZOOM = 1.25;
const WHEEL_ZOOM = 1.1;

export function clampScale(s: number): number {
  return Math.round(Math.min(8, Math.max(0.2, s)) * 100) / 100;
}

export function DiagramModal({ source, onClose }: Props) {
  const [result, setResult] = useState<MermaidResult | null>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  useEffect(() => {
    let live = true;
    void renderMermaid(source).then((r) => {
      if (live) setResult(r);
    });
    return () => {
      live = false;
    };
  }, [source]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        e.preventDefault();
        // Capture phase + stop: outer overlays (e.g. NoteView) close on a
        // bubble-phase window Escape and must not see this one.
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  const zoom = (factor: number): void => setScale((s) => clampScale(s * factor));
  const reset = (): void => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  };

  const toolButton = (label: string, icon: string, onClick: () => void) => (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="flex h-7 w-7 items-center justify-center rounded-sm text-ink-1 hover:bg-fog hover:text-ink-0"
    >
      <Lucide name={icon} size={14} />
    </button>
  );

  return createPortal(
    <div role="dialog" aria-label="diagram" className="fixed inset-0 z-[10000] flex flex-col bg-paper/95">
      <div className="flex items-center gap-1 border-b border-hairline px-3 py-2">
        <span className="font-mono text-10 uppercase tracking-[0.12em] text-ink-2">diagram</span>
        <div className="ml-auto flex items-center gap-1">
          {toolButton('zoom out', 'zoom-out', () => zoom(1 / BUTTON_ZOOM))}
          {toolButton('zoom in', 'zoom-in', () => zoom(BUTTON_ZOOM))}
          {toolButton('reset view', 'maximize', reset)}
          {toolButton('close diagram', 'x', onClose)}
        </div>
      </div>
      <div
        className="relative flex-1 cursor-grab overflow-hidden active:cursor-grabbing"
        onWheel={(e) => zoom(e.deltaY < 0 ? WHEEL_ZOOM : 1 / WHEEL_ZOOM)}
        onMouseDown={(e) => {
          drag.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y };
        }}
        onMouseMove={(e) => {
          const d = drag.current;
          if (!d) return;
          setOffset({ x: d.ox + e.clientX - d.x, y: d.oy + e.clientY - d.y });
        }}
        onMouseUp={() => {
          drag.current = null;
        }}
        onMouseLeave={() => {
          drag.current = null;
        }}
      >
        <div
          data-testid="diagram-canvas"
          className="absolute inset-0 flex items-center justify-center"
          style={{
            transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
            transformOrigin: 'center',
          }}
        >
          {result?.ok === true && <div dangerouslySetInnerHTML={{ __html: result.svg }} />}
          {result?.ok === false && (
            <div className="max-w-xl rounded border border-hairline bg-vellum p-4 text-12">
              <div className="text-oxblood">diagram error: {result.error}</div>
              <pre className="mt-2 whitespace-pre-wrap font-mono text-11 text-ink-1">{source}</pre>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
