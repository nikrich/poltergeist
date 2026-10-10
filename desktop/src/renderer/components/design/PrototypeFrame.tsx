import { useEffect, useRef, useState } from 'react';
import { Lucide } from '../Lucide';
import { designSession } from '../../stores/design-session';
import type { DesignSessionSnapshot } from '../../../shared/design-types';

/** Messages the prototype's host script (bundled by main) posts to us. */
type ProtoMessage =
  | { type: 'gb-proto:scroll'; y: number }
  | { type: 'gb-proto:route'; hash: string }
  | { type: 'gb-proto:error'; message: string };

function isProtoMessage(data: unknown): data is ProtoMessage {
  return (
    typeof data === 'object' &&
    data !== null &&
    typeof (data as { type?: unknown }).type === 'string' &&
    (data as { type: string }).type.startsWith('gb-proto:')
  );
}

function withHash(url: string, hash: string): string {
  const base = url.split('#')[0] ?? url;
  return hash.startsWith('#') && hash.length > 1 ? `${base}${hash}` : base;
}

/** Tag a dev-server URL with the revision so each swap is a fresh load. */
function withRev(url: string, rev: number): string {
  const base = url.split('#')[0] ?? url;
  return `${base}${base.includes('?') ? '&' : '?'}gbrev=${rev}`;
}

// No popups and no top navigation: a prototype could carry meeting content out
// through a window URL (main drops their popups too).
const SCRATCH_SANDBOX = 'allow-scripts allow-same-origin allow-forms';
const WORKTREE_SANDBOX = SCRATCH_SANDBOX;

interface Props {
  session: DesignSessionSnapshot;
  /** Post build/runtime errors to the sidecar. Only one window should, so the
   *  pop-out leaves it to the panel. */
  reportErrors?: boolean;
}

/** The live prototype, double-buffered: each new revision is bundled by main
 *  (scratch) or served by the worktree's dev server, loads in the hidden
 *  iframe at the current route, and swaps in on `load` with the scroll
 *  position restored — the frame never blanks. */
export function PrototypeFrame({ session, reportErrors = true }: Props) {
  const ui = session.canvases.ui;
  const dir = session.prototype_dir;
  const codebase = session.ui_kind === 'worktree' ? session.codebase : null;
  const worktree = codebase?.worktree ?? null;
  const appDir = codebase?.app_dir ?? null;
  // A repo picked by voice installs and runs nothing until confirmed.
  const unconfirmed = session.ui_kind === 'worktree' && !session.codebase_confirmed;
  const [servedFor, setServedFor] = useState<string | null>(null);
  const [slots, setSlots] = useState<[string | null, string | null]>([null, null]);
  const [front, setFront] = useState<0 | 1>(0);
  const [problem, setProblem] = useState<'build' | 'runtime' | null>(null);
  const frontRef = useRef<0 | 1>(0);
  const pendingSlot = useRef<0 | 1 | null>(null);
  const frameRefs = [useRef<HTMLIFrameElement>(null), useRef<HTMLIFrameElement>(null)];
  const lastY = useRef(0);
  const lastHash = useRef('');
  const reported = useRef(new Set<number>());
  const shownRev = useRef(0);

  const report = (rev: number, message: string) => {
    if (!reportErrors || reported.current.has(rev)) return;
    reported.current.add(rev);
    // The sidecar answers with a fix run; nothing to do here if it's gone.
    designSession.buildError(rev, message).catch(() => {});
  };

  useEffect(() => {
    if (ui.rev <= 0 || unconfirmed) return;
    let live = true;
    const rev = ui.rev;
    const show = (url: string) => {
      const back: 0 | 1 = frontRef.current === 0 ? 1 : 0;
      pendingSlot.current = back;
      shownRev.current = rev;
      setSlots((s) => {
        const next: [string | null, string | null] = [s[0], s[1]];
        next[back] = withHash(url, lastHash.current);
        return next;
      });
    };
    const fail = (message: string) => {
      setProblem('build');
      report(rev, message);
    };
    const failed = (e: unknown) => {
      if (live) fail(e instanceof Error ? e.message : String(e));
    };

    if (worktree && appDir) {
      // HMR has usually applied the change already; reloading the hidden
      // buffer covers full reloads and keeps the swap identical to scratch.
      window.gb.design.devserver
        .ensure(worktree, appDir)
        .then((res) => {
          if (!live) return;
          setServedFor(worktree);
          if (!res.ok) return fail(res.error);
          if (res.errors.length > 0) return fail(res.errors.join('\n'));
          show(withRev(res.url, rev));
        })
        .catch(failed);
      return () => {
        live = false;
        void window.gb.design.devserver.release(worktree);
      };
    }

    window.gb.design
      .build(dir, rev)
      .then((res) => {
        if (!live) return;
        if (!res.ok) {
          setProblem('build');
          report(res.rev, res.error);
          return;
        }
        show(res.url);
      })
      .catch(failed);
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dir, ui.rev, worktree, appDir, unconfirmed]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const frontWin = frameRefs[frontRef.current]?.current?.contentWindow;
      if (!frontWin || event.source !== frontWin || !isProtoMessage(event.data)) return;
      const msg = event.data;
      if (msg.type === 'gb-proto:scroll' && typeof msg.y === 'number') lastY.current = msg.y;
      if (msg.type === 'gb-proto:route' && typeof msg.hash === 'string') lastHash.current = msg.hash;
      if (msg.type === 'gb-proto:error' && typeof msg.message === 'string') {
        setProblem('runtime');
        report(shownRev.current, `Runtime error: ${msg.message}`);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onLoad = (slot: 0 | 1) => {
    if (pendingSlot.current !== slot) return;
    pendingSlot.current = null;
    frontRef.current = slot;
    setFront(slot);
    setProblem(null);
    frameRefs[slot]?.current?.contentWindow?.postMessage(
      { type: 'gb-proto:scroll', y: lastY.current },
      '*',
    );
  };

  if (ui.rev <= 0) {
    return (
      <div className="flex h-full min-h-[240px] flex-col items-center justify-center gap-2 text-center">
        <Lucide name="ear" size={18} className="text-ink-3" />
        <p className="m-0 text-13 text-ink-1">Listening for the first design discussion…</p>
        {ui.buffered_s > 0 && (
          <p className="m-0 font-mono text-11 text-ink-3">
            {Math.round(ui.buffered_s)}s of design talk buffered
          </p>
        )}
        {ui.running && <p className="m-0 font-mono text-11 text-ink-2">Building the first version…</p>}
      </div>
    );
  }

  return (
    <div className="relative h-full min-h-[min(560px,58vh)] overflow-hidden rounded-md border border-hairline bg-white">
      {([0, 1] as const).map((slot) => (
        <iframe
          key={slot}
          ref={frameRefs[slot]}
          title={`Prototype ${slot === front ? '' : '(next)'}`.trim()}
          data-front={slot === front ? 'true' : 'false'}
          src={slots[slot] ?? undefined}
          sandbox={worktree ? WORKTREE_SANDBOX : SCRATCH_SANDBOX}
          onLoad={() => onLoad(slot)}
          className="absolute inset-0 h-full w-full border-0"
          style={{ visibility: slot === front ? 'visible' : 'hidden' }}
        />
      ))}
      {worktree && servedFor !== worktree && (
        <div className="absolute inset-0 flex items-center justify-center gap-2 bg-paper font-mono text-11 text-ink-2">
          <Lucide name="loader" size={12} style={{ animation: 'gb-spin 0.9s linear infinite' }} />
          Starting dev server…
        </div>
      )}
      {problem && (
        <div
          role="status"
          className="absolute left-3 top-3 flex items-center gap-2 rounded-sm border border-oxblood/30 bg-paper/95 px-2 py-1 font-mono text-11 text-oxblood shadow-sm"
        >
          <Lucide name="alert-triangle" size={12} />
          {problem === 'build' ? 'Build failed — fixing…' : 'Prototype error — fixing…'}
        </div>
      )}
      {ui.running && (
        <div className="absolute right-3 top-3 flex items-center gap-[6px] rounded-full border border-hairline-2 bg-paper/90 px-2 py-[3px] font-mono text-10 text-ink-1 shadow-sm">
          <Lucide name="loader" size={11} style={{ animation: 'gb-spin 0.9s linear infinite' }} />
          Updating…
        </div>
      )}
    </div>
  );
}
