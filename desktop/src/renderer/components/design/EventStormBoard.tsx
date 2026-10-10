import { useMemo, useRef, useState } from 'react';
import { Lucide } from '../Lucide';
import { LANE_LABEL_W, layoutBoard } from './board-layout';
import type { BoardItemKind, BoardModel } from '../../../shared/design-types';

// intentional fixed colours: event-storming's sticky-note convention, the
// same in both themes; text stays dark on every one of them.
export const STICKY: Record<BoardItemKind, { bg: string; label: string }> = {
  event: { bg: '#f59e0b', label: 'Event' },
  command: { bg: '#60a5fa', label: 'Command' },
  aggregate: { bg: '#fde047', label: 'Aggregate' },
  policy: { bg: '#c4b5fd', label: 'Policy' },
  read_model: { bg: '#86efac', label: 'Read model' },
  external: { bg: '#f9a8d4', label: 'External system' },
  actor: { bg: '#fef9c3', label: 'Actor' },
  hotspot: { bg: '#fb7185', label: 'Hotspot' },
};

const MIN_SCALE = 0.3;
const MAX_SCALE = 2;
const STEP = 1.2;

function clamp(s: number): number {
  return Math.round(Math.min(MAX_SCALE, Math.max(MIN_SCALE, s)) * 100) / 100;
}

interface Props {
  model: BoardModel;
}

/** The event-storming board: lanes per bounded context, stickies along the
 *  timeline, arrows for links. Scrolls both ways; zoom with -/+/fit. */
export function EventStormBoard({ model }: Props) {
  const layout = useMemo(() => layoutBoard(model), [model]);
  const [scale, setScale] = useState(1);
  const viewport = useRef<HTMLDivElement>(null);

  const fit = () => {
    const el = viewport.current;
    if (!el || layout.width === 0) return;
    setScale(clamp(Math.min(el.clientWidth / layout.width, el.clientHeight / layout.height)));
  };

  const toolButton = (label: string, icon: string, onClick: () => void) => (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="flex h-6 w-6 items-center justify-center rounded-sm text-ink-1 hover:bg-fog hover:text-ink-0"
    >
      <Lucide name={icon} size={13} />
    </button>
  );

  if (layout.notes.length === 0) {
    return (
      <div className="flex h-full min-h-[240px] items-center justify-center text-13 text-ink-2">
        The board fills in as the domain is discussed.
      </div>
    );
  }

  const usedKinds = (Object.keys(STICKY) as BoardItemKind[]).filter((k) =>
    layout.notes.some((n) => n.kind === k),
  );

  return (
    <div className="flex h-full min-h-[240px] flex-col">
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        {usedKinds.map((k) => (
          <span key={k} className="flex items-center gap-[5px] text-11 text-ink-2">
            <span className="h-[10px] w-[10px] rounded-[2px]" style={{ background: STICKY[k].bg }} />
            {STICKY[k].label}
          </span>
        ))}
        <div className="ml-auto flex items-center gap-[2px]">
          {toolButton('Zoom out', 'zoom-out', () => setScale((s) => clamp(s / STEP)))}
          <span className="w-9 text-center font-mono text-10 text-ink-2">{Math.round(scale * 100)}%</span>
          {toolButton('Zoom in', 'zoom-in', () => setScale((s) => clamp(s * STEP)))}
          {toolButton('Fit board', 'maximize', fit)}
        </div>
      </div>
      <div
        ref={viewport}
        className="flex-1 overflow-auto rounded-md border border-hairline bg-paper"
        data-testid="board-viewport"
      >
        <div style={{ width: layout.width * scale, height: layout.height * scale }}>
          <div
            className="relative"
            style={{
              width: layout.width,
              height: layout.height,
              transform: `scale(${scale})`,
              transformOrigin: '0 0',
            }}
          >
            {layout.lanes.map((lane, i) => (
              <div
                key={lane.id}
                className={`absolute left-0 right-0 ${i > 0 ? 'border-t border-dashed border-hairline-2' : ''}`}
                style={{ top: lane.y, height: lane.height }}
              >
                <div
                  className="absolute left-3 top-3 font-mono text-10 uppercase tracking-eyebrow-loose text-ink-2"
                  style={{ width: LANE_LABEL_W - 24 }}
                >
                  {lane.name}
                </div>
              </div>
            ))}
            <svg
              className="pointer-events-none absolute inset-0"
              width={layout.width}
              height={layout.height}
              aria-hidden="true"
            >
              <defs>
                <marker
                  id="gb-board-arrow"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto-start-reverse"
                >
                  <path d="M0,0 L10,5 L0,10 z" fill="var(--ink-2)" />
                </marker>
              </defs>
              {layout.arrows.map((a) => (
                <line
                  key={`${a.from}->${a.to}`}
                  x1={a.x1}
                  y1={a.y1}
                  x2={a.x2}
                  y2={a.y2}
                  stroke="var(--ink-2)"
                  strokeWidth={1.5}
                  markerEnd="url(#gb-board-arrow)"
                />
              ))}
            </svg>
            {layout.notes.map((n) => (
              <div
                key={n.id}
                data-kind={n.kind}
                title={`${STICKY[n.kind].label}: ${n.label}`}
                className="absolute flex items-center justify-center overflow-hidden rounded-[3px] p-2 text-center text-12 leading-[1.25] text-[#0E0F12] shadow-card"
                style={{
                  left: n.x,
                  top: n.y,
                  width: n.w,
                  height: n.h,
                  background: STICKY[n.kind].bg,
                  transform: n.kind === 'hotspot' ? 'rotate(-4deg)' : undefined,
                  fontSize: n.kind === 'actor' ? 11 : undefined,
                }}
              >
                {n.label}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
