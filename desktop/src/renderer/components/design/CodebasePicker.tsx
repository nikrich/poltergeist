import { useEffect, useRef, useState } from 'react';
import { Lucide } from '../Lucide';
import { Pill } from '../Pill';
import { useCodebases } from '../../lib/api/hooks';
import { designSession, useDesignSession } from '../../stores/design-session';
import { toast } from '../../stores/toast';
import type { DesignSessionSnapshot } from '../../../shared/design-types';

const LOCKED_HINT = 'The prototype already has revisions — start a new session to switch codebase';

function chipLabel(session: DesignSessionSnapshot): string {
  if (session.codebase) return `${session.codebase.name} · ${session.codebase.branch}`;
  // Chosen but not created yet (the worktree is made when the canvas starts).
  return session.ui_kind === 'worktree' ? 'Existing repo' : 'Scratch';
}

/** Header chip: what the prototype is built on (a scratch folder or a git
 *  worktree of an existing app), switchable until the first revision. */
export function CodebasePicker({ session }: { session: DesignSessionSnapshot }) {
  const open = useDesignSession((s) => s.pickerOpen);
  const setOpen = useDesignSession((s) => s.setPickerOpen);
  const [q, setQ] = useState('');
  const root = useRef<HTMLDivElement>(null);
  const locked = session.canvases.ui.rev > 0;
  const results = useCodebases(q.trim(), { enabled: open && !locked });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      window.removeEventListener('keydown', onKey);
    };
  }, [open, setOpen]);

  const choose = (path: string | null) => {
    setOpen(false);
    setQ('');
    designSession.codebase(path).catch((e: unknown) => {
      toast.error(`Codebase change failed: ${e instanceof Error ? e.message : String(e)}`);
    });
  };

  const label = chipLabel(session);
  const current = session.codebase?.repo ?? null;

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-label={`Codebase: ${label}`}
        aria-expanded={open && !locked}
        disabled={locked}
        title={locked ? LOCKED_HINT : 'Build on an existing repo or a scratch prototype'}
        onClick={() => setOpen(!open)}
        className="flex max-w-[240px] cursor-pointer items-center gap-[5px] rounded-sm border border-hairline-2 bg-paper px-2 py-[3px] font-mono text-11 text-ink-0 disabled:cursor-not-allowed disabled:opacity-60"
      >
        <Lucide name={session.ui_kind === 'worktree' ? 'git-branch' : 'app-window'} size={11} className="text-ink-2" />
        <span className="truncate">{label}</span>
      </button>
      {open && !locked && (
        <div
          role="dialog"
          aria-label="Choose codebase"
          className="absolute left-0 top-[calc(100%+4px)] z-20 flex w-[320px] flex-col gap-2 rounded-md border border-hairline bg-vellum p-2 shadow-md"
        >
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search repos…"
            className="rounded-sm border border-hairline-2 bg-paper px-2 py-[5px] text-12 text-ink-0 placeholder:text-ink-3 focus:outline-none"
          />
          <div role="listbox" aria-label="Codebases" className="flex max-h-[280px] flex-col overflow-y-auto">
            <button
              type="button"
              role="option"
              aria-selected={session.ui_kind === 'scratch'}
              onClick={() => choose(null)}
              className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-[6px] text-left text-12 text-ink-0 hover:bg-paper"
            >
              <Lucide name="app-window" size={12} className="text-ink-2" />
              <span className="flex-1">Scratch prototype</span>
            </button>
            {results.isLoading && <p className="m-0 px-2 py-[6px] text-12 text-ink-3">Scanning repos…</p>}
            {results.isError && (
              <p className="m-0 px-2 py-[6px] text-12 text-oxblood">Could not list repos</p>
            )}
            {results.data?.length === 0 && (
              <p className="m-0 px-2 py-[6px] text-12 text-ink-3">No repos match</p>
            )}
            {(results.data ?? []).map((c) => (
              <button
                key={c.path}
                type="button"
                role="option"
                aria-selected={c.path === current}
                onClick={() => choose(c.path)}
                className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-[6px] text-left hover:bg-paper"
              >
                <Lucide name="git-branch" size={12} className="text-ink-2" />
                <span className="flex min-w-0 flex-1 flex-col leading-[1.3]">
                  <span className="truncate text-12 text-ink-0">{c.name}</span>
                  <span className="truncate font-mono text-10 text-ink-3">{c.rel}</span>
                </span>
                {c.frontend && <Pill tone="outline">frontend</Pill>}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
