import { useEffect, useRef, useState } from 'react';
import { Btn } from '../Btn';
import { Eyebrow } from '../Eyebrow';
import { Lucide } from '../Lucide';
import { ArchitectureView } from './ArchitectureView';
import { CodebasePicker } from './CodebasePicker';
import { EventStormBoard } from './EventStormBoard';
import { PrototypeFrame } from './PrototypeFrame';
import { useDesignPacks, useProjects } from '../../lib/api/hooks';
import {
  confirmCodebase,
  designSession,
  isDesignOpen,
  useDesignSession,
} from '../../stores/design-session';
import { toast } from '../../stores/toast';
import type {
  CanvasSnapshot,
  DesignCanvas,
  DesignSessionSnapshot,
} from '../../../shared/design-types';

const CANVAS_NAME: Record<DesignCanvas, string> = { ui: 'Prototype', board: 'Board' };
const PILL_NAME: Record<DesignCanvas, string> = { ui: 'UI', board: 'Board' };

const selectClass =
  'max-w-[160px] cursor-pointer truncate rounded-sm border border-hairline-2 bg-paper px-2 py-[3px] font-mono text-11 text-ink-0';

function run(action: Promise<unknown>, what: string): Promise<unknown> {
  return action.catch((e: unknown) => {
    toast.error(`${what} failed: ${e instanceof Error ? e.message : String(e)}`);
    throw e;
  });
}

function pillText(canvas: DesignCanvas, c: CanvasSnapshot): string {
  if (c.running) return 'Updating…';
  switch (c.state) {
    case 'active':
      return `Listening · ${PILL_NAME[canvas]}`;
    case 'paused':
      return 'Paused';
    case 'ended':
      return 'Ended';
    case 'unavailable':
      return 'Unavailable';
    default:
      return 'Off';
  }
}

function StatePill({ canvas, snapshot }: { canvas: DesignCanvas; snapshot: CanvasSnapshot }) {
  const live = snapshot.state === 'active' || snapshot.running;
  return (
    <span
      data-pill
      className={`inline-flex items-center gap-[5px] whitespace-nowrap rounded-sm px-[7px] py-[2px] font-mono text-10 font-medium ${
        live ? 'bg-neon/15 text-neon-ink' : snapshot.state === 'unavailable' ? 'bg-oxblood/15 text-pill-oxblood-fg' : 'bg-fog text-ink-1'
      }`}
    >
      {pillText(canvas, snapshot)}
    </span>
  );
}

/** Shown while no canvas has started: one line, two ways in. */
function CollapsedBar() {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-hairline bg-vellum px-5 py-3">
      <Lucide name="layout-template" size={14} className="text-ink-2" />
      <span className="flex-1 text-13 text-ink-1">
        Design: say &ldquo;let&apos;s kick off a frontend prototype&rdquo; or press Start
      </span>
      <Btn
        variant="secondary"
        size="sm"
        onClick={() => void run(designSession.start('ui'), 'Start').catch(() => {})}
      >
        Start prototype
      </Btn>
      <Btn
        variant="ghost"
        size="sm"
        onClick={() => void run(designSession.start('board'), 'Start').catch(() => {})}
      >
        Start board
      </Btn>
    </div>
  );
}

/** A repo named in the meeting is only used once someone says yes here. */
function ConfirmCodebase({ name, onUse, onScratch }: { name: string; onUse: () => void; onScratch: () => void }) {
  return (
    <div className="flex h-full min-h-[240px] flex-col items-center justify-center gap-3 text-center">
      <Lucide name="git-branch" size={18} className="text-ink-3" />
      <p className="m-0 max-w-[460px] text-13 leading-[1.5] text-ink-1">
        Build on <strong className="font-medium text-ink-0">{name}</strong>? Poltergeist will create a
        worktree, install its dependencies and run its dev server (sandboxed, no backend).
      </p>
      <div className="flex gap-2">
        <Btn variant="secondary" size="sm" icon={<Lucide name="git-branch" size={12} />} onClick={onUse}>
          Use {name}
        </Btn>
        <Btn variant="ghost" size="sm" icon={<Lucide name="app-window" size={12} />} onClick={onScratch}>
          Scratch instead
        </Btn>
      </div>
    </div>
  );
}

/** Live design beside the transcript: header (project, design system, state),
 *  Prototype | Board tabs, and the controls footer. */
export function DesignPanel() {
  const session = useDesignSession((s) => s.session);
  if (!session || !isDesignOpen(session)) return <CollapsedBar />;
  return <ExpandedPanel session={session} />;
}

function ExpandedPanel({ session }: { session: DesignSessionSnapshot }) {
  const projects = useProjects();
  const packs = useDesignPacks();
  const [view, setView] = useState<DesignCanvas>(session.focus ?? 'ui');
  const [boardMode, setBoardMode] = useState<'stickies' | 'architecture'>('stickies');
  const [nudge, setNudge] = useState('');
  const [target, setTarget] = useState<number | null>(null);
  const [ejected, setEjected] = useState<string | null>(null);

  // A spoken "let's focus on the backend" brings that canvas into view;
  // clicking a tab afterwards only changes what is shown.
  useEffect(() => {
    if (session.focus) setView(session.focus);
  }, [session.focus]);

  const canvas = session.canvases[view];
  const focus = session.focus ?? view;
  const live = canvas.state === 'active' || canvas.state === 'paused';

  useEffect(() => setTarget(null), [view, canvas.rev]);

  const latest = useRef({ view, live });
  latest.current = { view, live };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || !e.shiftKey || e.key.toLowerCase() !== 'u') return;
      e.preventDefault();
      if (latest.current.live) {
        void run(designSession.update(latest.current.view), 'Update').catch(() => {});
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const sendNudge = () => {
    const text = nudge.trim();
    if (!text) return;
    run(designSession.nudge(text, view), 'Nudge')
      .then(() => setNudge(''))
      .catch(() => {});
  };

  const revNumbers = canvas.revs.map((r) => r.rev).sort((a, b) => a - b);
  const cursor = target ?? canvas.rev;
  const prevRev = [...revNumbers].reverse().find((r) => r < cursor);
  const nextRev = revNumbers.find((r) => r > cursor && r <= canvas.rev);
  const stepTo = (rev: number | undefined) => {
    if (rev === undefined) return;
    setTarget(rev === canvas.rev ? null : rev);
  };

  // A repo that can't be prepared (no frontend, install failed) can still be
  // swapped for a scratch prototype while nothing has been built.
  const worktree = session.ui_kind === 'worktree';
  const canBackOut = view === 'ui' && worktree && canvas.rev === 0;
  const switchToScratch = () => void run(designSession.codebase(null), 'Codebase change').catch(() => {});

  const eject = () => {
    run(designSession.eject(), 'Eject')
      .then((res) => setEjected((res as { path: string }).path))
      .catch(() => {});
  };

  return (
    <div className="flex min-h-[min(760px,78vh)] flex-col rounded-lg border border-hairline bg-vellum p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Eyebrow className="m-0">live design</Eyebrow>
        <select
          aria-label="Project"
          value={session.project_id ?? ''}
          onChange={(e) =>
            void run(designSession.config({ project_id: e.target.value || null }), 'Project change').catch(
              () => {},
            )
          }
          className={selectClass}
        >
          <option value="">No project</option>
          {(projects.data ?? [])
            .filter((p) => !p.archived || p.id === session.project_id)
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
        </select>
        <select
          aria-label="Design system"
          value={session.pack_id}
          onChange={(e) =>
            void run(designSession.config({ pack_id: e.target.value }), 'Design system change').catch(
              () => {},
            )
          }
          className={selectClass}
        >
          {!(packs.data ?? []).some((p) => p.id === session.pack_id) && (
            <option value={session.pack_id}>{session.pack_id}</option>
          )}
          {(packs.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <CodebasePicker session={session} />
        <div className="flex-1" />
        <StatePill canvas={focus} snapshot={session.canvases[focus]} />
      </div>

      <div role="tablist" aria-label="Design canvas" className="mb-3 flex gap-1 border-b border-hairline">
        {(['ui', 'board'] as const).map((c) => (
          <button
            key={c}
            type="button"
            role="tab"
            aria-selected={view === c}
            data-focused={session.focus === c ? 'true' : 'false'}
            onClick={() => setView(c)}
            className={`-mb-px flex cursor-pointer items-center gap-[6px] border-b-2 px-3 py-[6px] text-12 ${
              view === c ? 'border-neon text-ink-0' : 'border-transparent text-ink-2 hover:text-ink-0'
            }`}
          >
            {CANVAS_NAME[c]}
            {session.focus === c && (
              <span aria-hidden="true" title="Focused" className="h-[6px] w-[6px] rounded-full bg-neon" />
            )}
          </button>
        ))}
        {view === 'board' && canvas.state !== 'off' && (
          <div className="ml-auto flex items-center gap-[2px] pb-1">
            {(['stickies', 'architecture'] as const).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={boardMode === m}
                onClick={() => setBoardMode(m)}
                className={`cursor-pointer rounded-sm px-2 py-[2px] font-mono text-11 ${
                  boardMode === m ? 'bg-neon/15 text-neon-ink' : 'text-ink-2 hover:text-ink-0'
                }`}
              >
                {m === 'stickies' ? 'Stickies' : 'Architecture'}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="min-h-[min(560px,58vh)] flex-1">
        {canvas.state === 'off' ? (
          <div className="flex h-full min-h-[240px] flex-col items-center justify-center gap-3 text-center">
            <p className="m-0 text-13 text-ink-2">
              {view === 'ui'
                ? 'No prototype yet. Start one to turn the UI talk into a working React app.'
                : 'No board yet. Start one to map the domain as it is discussed.'}
            </p>
            <Btn
              variant="secondary"
              size="sm"
              onClick={() => void run(designSession.start(view), 'Start').catch(() => {})}
            >
              {view === 'ui' ? 'Start prototype' : 'Start board'}
            </Btn>
          </div>
        ) : canvas.state === 'unavailable' ? (
          <div className="flex flex-col items-start gap-3">
            <p className="m-0 text-13 leading-[1.5] text-ink-1">
              Live design is unavailable — {canvas.reason ?? 'unknown error'}.
            </p>
            {canBackOut && (
              <Btn
                variant="secondary"
                size="sm"
                icon={<Lucide name="app-window" size={12} />}
                onClick={switchToScratch}
              >
                Use scratch instead
              </Btn>
            )}
          </div>
        ) : view === 'ui' && worktree && !session.codebase_confirmed && session.codebase ? (
          <ConfirmCodebase name={session.codebase.name} onUse={confirmCodebase} onScratch={switchToScratch} />
        ) : view === 'ui' && worktree && session.install === 'running' && canvas.rev === 0 ? (
          <div className="flex h-full min-h-[240px] flex-col items-center justify-center gap-2 text-center">
            <Lucide name="loader" size={18} className="text-ink-3" style={{ animation: 'gb-spin 0.9s linear infinite' }} />
            <p className="m-0 text-13 text-ink-1">Installing dependencies…</p>
            {session.codebase && (
              <p className="m-0 font-mono text-11 text-ink-3">{session.codebase.name}</p>
            )}
          </div>
        ) : view === 'ui' ? (
          <PrototypeFrame session={session} />
        ) : boardMode === 'architecture' && session.board ? (
          <ArchitectureView model={session.board} />
        ) : (
          <EventStormBoard model={session.board ?? { contexts: [], items: [], links: [] }} />
        )}
      </div>

      {canvas.state !== 'off' && (
        <div className="mt-3 flex flex-col gap-2 border-t border-hairline pt-3">
          {live && (
            <input
              value={nudge}
              onChange={(e) => setNudge(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  sendNudge();
                }
              }}
              placeholder={view === 'ui' ? 'Nudge the prototype… (Enter sends)' : 'Nudge the board… (Enter sends)'}
              className="rounded-sm border border-hairline-2 bg-paper px-2 py-[6px] text-12 text-ink-0 placeholder:text-ink-3 focus:outline-none"
            />
          )}
          <div className="flex flex-wrap items-center gap-2">
            {live && (
              <Btn
                variant="secondary"
                size="sm"
                icon={<Lucide name="refresh-cw" size={12} />}
                onClick={() => void run(designSession.update(view), 'Update').catch(() => {})}
              >
                Update now
              </Btn>
            )}
            {canvas.state === 'active' && (
              <Btn
                variant="ghost"
                size="sm"
                icon={<Lucide name="pause" size={12} />}
                onClick={() => void run(designSession.pause(view), 'Pause').catch(() => {})}
              >
                Pause
              </Btn>
            )}
            {canvas.state === 'paused' && (
              <Btn
                variant="ghost"
                size="sm"
                icon={<Lucide name="play" size={12} />}
                onClick={() => void run(designSession.resume(view), 'Resume').catch(() => {})}
              >
                Resume
              </Btn>
            )}
            {view === 'ui' && canvas.state === 'ended' && !worktree && (
              <Btn
                variant="secondary"
                size="sm"
                icon={<Lucide name="package" size={12} />}
                onClick={eject}
              >
                Eject
              </Btn>
            )}
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="external-link" size={12} />}
              onClick={() => void window.gb.design.openPopout()}
            >
              Pop out
            </Btn>
            <div className="flex-1" />
            {canvas.rev > 0 && (
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  aria-label="Previous revision"
                  disabled={prevRev === undefined}
                  onClick={() => stepTo(prevRev)}
                  className="flex h-6 w-6 cursor-pointer items-center justify-center rounded-sm text-ink-1 hover:bg-fog disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Lucide name="chevron-left" size={13} />
                </button>
                <span className="font-mono text-11 tabular-nums text-ink-1">rev {cursor}</span>
                <button
                  type="button"
                  aria-label="Next revision"
                  disabled={nextRev === undefined}
                  onClick={() => stepTo(nextRev)}
                  className="flex h-6 w-6 cursor-pointer items-center justify-center rounded-sm text-ink-1 hover:bg-fog disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Lucide name="chevron-right" size={13} />
                </button>
              </div>
            )}
          </div>
          {target !== null && (
            <div className="flex items-center gap-3 rounded-sm bg-paper px-3 py-2 text-12 text-ink-1">
              <span className="flex-1">
                Restore rev {target}?
                {canvas.revs.find((r) => r.rev === target)?.summary && (
                  <span className="ml-2 text-ink-3">
                    {canvas.revs.find((r) => r.rev === target)?.summary}
                  </span>
                )}
              </span>
              <button
                type="button"
                className="cursor-pointer text-11 font-medium text-ink-0 hover:underline"
                onClick={() => {
                  const rev = target;
                  setTarget(null);
                  void run(designSession.revert(view, rev), 'Restore').catch(() => {});
                }}
              >
                Restore
              </button>
              <button
                type="button"
                className="cursor-pointer text-11 text-ink-2 hover:text-ink-0"
                onClick={() => setTarget(null)}
              >
                Cancel
              </button>
            </div>
          )}
          {ejected && (
            <div className="flex items-center gap-3 rounded-sm bg-paper px-3 py-2">
              <span className="min-w-0 flex-1 truncate font-mono text-11 text-ink-1">{ejected}</span>
              <button
                type="button"
                className="cursor-pointer text-11 text-ink-1 hover:text-ink-0"
                onClick={() => void window.gb.shell.showItemInFolder(ejected)}
              >
                Show in folder
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
