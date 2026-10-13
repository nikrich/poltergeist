import { useState } from 'react';
import { ArchitectureView } from '../components/design/ArchitectureView';
import { BoardModeToggle, type BoardMode } from '../components/design/BoardModeToggle';
import { EventStormBoard } from '../components/design/EventStormBoard';
import { PrototypeFrame } from '../components/design/PrototypeFrame';
import { useDesignSession, useDesignSessionStream } from '../stores/design-session';

export const DESIGN_POPOUT_HASH = '#/design-popout';

export function isDesignPopoutRoute(hash: string = window.location.hash): boolean {
  return hash.startsWith(DESIGN_POPOUT_HASH);
}

/** The pop-out window for screen-sharing: only the focused canvas, full
 *  window, under a slim status bar. Follows the design stream on its own. */
export function DesignPopout() {
  useDesignSessionStream(true);
  const session = useDesignSession((s) => s.session);
  const canvas = session?.focus ?? 'ui';
  const snapshot = session?.canvases[canvas];
  const [boardMode, setBoardMode] = useState<BoardMode>('stickies');
  const showBoard = canvas === 'board' && !!snapshot && snapshot.state !== 'off';

  return (
    <div className="flex h-full flex-col bg-paper text-ink-0">
      <div className="flex h-8 flex-shrink-0 items-center gap-2 border-b border-hairline px-3 font-mono text-11 text-ink-2">
        <span className="text-ink-1">Live design</span>
        {session?.recording_title && (
          <>
            <span aria-hidden="true">·</span>
            <span className="truncate">{session.recording_title}</span>
          </>
        )}
        {snapshot?.running && (
          <>
            <span aria-hidden="true">·</span>
            <span className="text-neon-ink">Updating…</span>
          </>
        )}
        {snapshot?.state === 'paused' && (
          <>
            <span aria-hidden="true">·</span>
            <span>Paused</span>
          </>
        )}
        {showBoard && <BoardModeToggle mode={boardMode} onChange={setBoardMode} className="ml-auto" />}
      </div>
      <div className="min-h-0 flex-1 p-2">
        {!session || !snapshot || snapshot.state === 'off' ? (
          <div className="flex h-full items-center justify-center text-13 text-ink-2">
            Waiting for a live design session…
          </div>
        ) : canvas === 'ui' ? (
          <PrototypeFrame session={session} reportErrors={false} />
        ) : boardMode === 'architecture' && session.board ? (
          <ArchitectureView model={session.board} />
        ) : (
          <EventStormBoard model={session.board ?? { contexts: [], items: [], links: [] }} />
        )}
      </div>
    </div>
  );
}
