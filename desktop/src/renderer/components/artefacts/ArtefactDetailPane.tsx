import { useState } from 'react';
import { Btn } from '../Btn';
import { Lucide } from '../Lucide';
import { Pill } from '../Pill';
import { PanelError } from '../PanelError';
import { SkeletonRows } from '../SkeletonRows';
import { ArchitectureView } from '../design/ArchitectureView';
import { EventStormBoard } from '../design/EventStormBoard';
import { ArtefactPrototype, ArtefactWorktree } from './ArtefactPreview';
import { KIND_ICON, KIND_LABEL } from './kinds';
import { useArtefact, useEjectArtefact, useRemoveWorktree } from '../../lib/api/hooks';
import { useNoteView } from '../../stores/note-view';
import { toast } from '../../stores/toast';
import type { ArtefactDetail } from '../../../shared/design-types';

type Tab = 'preview' | 'board' | 'revisions';

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** One artefact: header with its meeting, actions, and Preview | Board | Revisions. */
export function ArtefactDetailPane({ id }: { id: string }) {
  const detail = useArtefact(id);
  if (detail.isLoading) return <SkeletonRows count={4} height={40} />;
  if (detail.isError || !detail.data) {
    return (
      <PanelError
        message={detail.error instanceof Error ? detail.error.message : 'could not load the artefact'}
        onRetry={() => detail.refetch()}
      />
    );
  }
  return <Detail detail={detail.data} />;
}

function Detail({ detail }: { detail: ArtefactDetail }) {
  const openNote = useNoteView((s) => s.open);
  const eject = useEjectArtefact();
  const removeWorktree = useRemoveWorktree();
  const tabs: Tab[] = [
    ...(detail.kind !== 'board' ? (['preview'] as const) : []),
    ...(detail.board_model ? (['board'] as const) : []),
    'revisions',
  ];
  const [tab, setTab] = useState<Tab>(tabs[0]!);
  const [boardMode, setBoardMode] = useState<'stickies' | 'architecture'>('stickies');

  const codebase = detail.codebase;
  const liveWorktree = detail.kind === 'worktree' && codebase && !codebase.missing ? codebase.worktree : null;
  // The code lives in the worktree; the folder holds the note, board and session log.
  const target = liveWorktree ?? detail.folder;

  const open = async (how: 'editor' | 'finder') => {
    const r = await window.gb.design.openPath(target, how);
    if (!r.ok) toast.error(r.error ?? 'could not open the folder');
  };

  const doEject = () => {
    eject
      .mutateAsync(detail.id)
      .then((r) => toast.success(`ejected to ${r.path}`))
      .catch((e: unknown) => toast.error(`eject failed: ${errMsg(e)}`));
  };

  const doRemove = () => {
    if (!codebase) return;
    if (
      !window.confirm(
        `Remove the worktree at ${codebase.worktree}? The branch ${codebase.branch} is kept if it has unmerged commits.`,
      )
    ) {
      return;
    }
    removeWorktree
      .mutateAsync(detail.id)
      .then((r) => {
        if (!r.removed) toast.error(r.reason ?? 'could not remove the worktree');
        else if (r.branch_kept) toast.info(`worktree removed — kept branch ${codebase.branch} (unmerged commits)`);
        else toast.success('worktree removed');
      })
      .catch((e: unknown) => toast.error(`remove failed: ${errMsg(e)}`));
  };

  const revs = [...detail.revs].sort((a, b) => b.rev - a.rev);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <header className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <Lucide name={KIND_ICON[detail.kind]} size={16} color="var(--ink-2)" />
          <h2 className="m-0 min-w-0 flex-1 truncate font-display text-20 font-semibold tracking-tight-xx text-ink-0">
            {detail.title}
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2 font-mono text-11 text-ink-2">
          <Pill tone="fog">{KIND_LABEL[detail.kind]}</Pill>
          {detail.board && detail.kind !== 'board' && <Pill tone="fog">board</Pill>}
          <span>{detail.date}</span>
          <span aria-hidden="true">·</span>
          <span>{detail.project ?? detail.context}</span>
          {codebase && (
            <>
              <span aria-hidden="true">·</span>
              <span>
                {codebase.name} · {codebase.branch}
              </span>
              {codebase.missing && <Pill tone="oxblood">worktree missing</Pill>}
            </>
          )}
          {detail.meeting_path && (
            <>
              <span aria-hidden="true">·</span>
              <button
                type="button"
                aria-label={`Open meeting note: ${detail.meeting ?? 'meeting'}`}
                onClick={() => openNote(detail.meeting_path!)}
                className="inline-flex cursor-pointer items-center gap-[5px] text-ink-1 hover:text-ink-0 hover:underline"
              >
                <Lucide name="mic" size={11} />
                {detail.meeting ?? 'meeting note'}
              </button>
            </>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Btn variant="secondary" size="sm" icon={<Lucide name="code" size={12} />} onClick={() => void open('editor')}>
            Open in editor
          </Btn>
          <Btn variant="ghost" size="sm" icon={<Lucide name="folder-open" size={12} />} onClick={() => void open('finder')}>
            Reveal in Finder
          </Btn>
          {detail.kind === 'prototype' && (
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="package" size={12} />}
              disabled={eject.isPending}
              onClick={doEject}
            >
              Eject
            </Btn>
          )}
          {detail.kind === 'worktree' && codebase && (
            <Btn
              variant="danger"
              size="sm"
              icon={<Lucide name="trash-2" size={12} />}
              disabled={removeWorktree.isPending}
              onClick={doRemove}
            >
              Remove worktree
            </Btn>
          )}
        </div>
      </header>

      <div role="tablist" aria-label="Artefact view" className="flex gap-1 border-b border-hairline">
        {tabs.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`-mb-px cursor-pointer border-b-2 px-3 py-[6px] text-12 ${
              tab === t ? 'border-neon text-ink-0' : 'border-transparent text-ink-2 hover:text-ink-0'
            }`}
          >
            {t === 'preview' ? 'Preview' : t === 'board' ? 'Board' : 'Revisions'}
          </button>
        ))}
        {tab === 'board' && (
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

      <div className="min-h-0 flex-1">
        {tab === 'preview' &&
          (detail.kind === 'worktree' ? <ArtefactWorktree detail={detail} /> : <ArtefactPrototype detail={detail} />)}
        {tab === 'board' &&
          detail.board_model &&
          (boardMode === 'architecture' ? (
            <ArchitectureView model={detail.board_model} />
          ) : (
            <EventStormBoard model={detail.board_model} />
          ))}
        {tab === 'revisions' &&
          (revs.length === 0 ? (
            <p className="m-0 text-13 text-ink-2">No revisions recorded.</p>
          ) : (
            <ol className="m-0 flex list-none flex-col gap-1 p-0">
              {revs.map((r) => (
                <li
                  key={r.rev}
                  data-testid="artefact-rev"
                  className="flex items-baseline gap-3 rounded-sm px-2 py-[6px] hover:bg-vellum"
                >
                  <span className="w-[52px] flex-shrink-0 font-mono text-11 tabular-nums text-ink-1">rev {r.rev}</span>
                  <span className="min-w-0 flex-1 text-13 text-ink-0">{r.summary}</span>
                  {r.at && (
                    <span className="font-mono text-10 text-ink-3">
                      {new Date(r.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          ))}
      </div>
    </div>
  );
}
