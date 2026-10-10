import { useState } from 'react';
import { useHistoryVersion, useNoteHistory } from '../lib/api/hooks';
import { formatRelativeTime } from '../lib/format';
import { sameBody } from '../lib/use-guarded-save';
import type { HistoryEntry } from '../../shared/api-types';
import { toast } from '../stores/toast';
import { Btn } from './Btn';
import { LineDiffView } from './LineDiffView';
import { Lucide } from './Lucide';

/** Short label for the writer a snapshot was taken before. Shared with spec B's Changes screen. */
export function actorLabel(actor: string): string {
  if (actor === 'user') return 'you';
  if (actor === 'assistant') return '✦ assistant';
  if (actor === 'mcp') return '⌁ mcp';
  if (actor === 'restore') return '↺ restore';
  if (actor.startsWith('plugin:')) return `⧉ ${actor.slice('plugin:'.length)}`;
  if (actor.startsWith('worker:')) return `⚙ ${actor.slice('worker:'.length)}`;
  return actor;
}

// The same content can be snapshotted twice, so a blob alone is not a key.
const entryKey = (e: HistoryEntry): string => `${e.ts}|${e.blob}`;

interface Props {
  path: string;
  onClose: () => void;
  /** Restores `entry` through the editor guard; rejects with a user-facing message. */
  onRestore: (entry: HistoryEntry) => Promise<void>;
}

/** Spec A3: timeline of versions, actor badge, diff against the current file, restore. */
export function HistoryDrawer({ path, onClose, onRestore }: Props) {
  const history = useNoteHistory(path);
  const items = history.data?.items ?? [];
  const [picked, setPicked] = useState<string | null>(null);
  const selected = items.find((e) => entryKey(e) === picked) ?? items[0] ?? null;
  const version = useHistoryVersion(path, selected?.blob ?? null);
  const [restoring, setRestoring] = useState(false);
  const current = version.data?.current ?? null;
  const unchanged =
    version.data !== undefined && current !== null && sameBody(version.data.content, current);

  const restore = async () => {
    if (!selected) return;
    setRestoring(true);
    try {
      await onRestore(selected);
      toast.success('version restored — the replaced text is in history');
      onClose();
    } catch (err) {
      toast.error(`restore failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setRestoring(false);
    }
  };

  return (
    <aside
      role="dialog"
      aria-label="page history"
      className="fixed inset-y-0 right-0 z-50 flex w-[760px] max-w-[94vw] flex-col border-l border-hairline bg-paper shadow-xl"
      onClick={(e) => e.stopPropagation()}
    >
      <header className="flex items-center gap-2 border-b border-hairline px-4 py-3">
        <Lucide name="history" size={14} color="var(--ink-2)" />
        <div className="flex-1 text-13 font-medium text-ink-0">page history</div>
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="x" size={14} />}
          onClick={onClose}
          ariaLabel="close history"
        />
      </header>
      <div className="flex min-h-0 flex-1">
        <ol aria-label="versions" className="w-[240px] flex-shrink-0 overflow-y-auto border-r border-hairline">
          {history.isLoading && <li className="p-4 text-11 text-ink-3">loading…</li>}
          {history.isError && (
            <li className="p-4 text-11 text-ink-3">
              history unavailable{' '}
              <button type="button" className="underline" onClick={() => void history.refetch()}>
                retry
              </button>
            </li>
          )}
          {history.isSuccess && items.length === 0 && (
            <li className="p-4 text-11 text-ink-3">
              no earlier versions yet — they appear after the note is edited
            </li>
          )}
          {items.map((e) => {
            const active = selected !== null && entryKey(e) === entryKey(selected);
            return (
              <li key={entryKey(e)}>
                <button
                  type="button"
                  title={e.ts}
                  aria-current={active ? 'true' : undefined}
                  onClick={() => setPicked(entryKey(e))}
                  className={`w-full px-4 py-2 text-left hover:bg-fog/50 ${active ? 'bg-fog/60' : ''}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-12 text-ink-0">{formatRelativeTime(e.ts)}</span>
                    <span
                      data-testid="actor-badge"
                      className="rounded-sm border border-hairline px-1 font-mono text-10 text-ink-2"
                    >
                      {actorLabel(e.actor)}
                    </span>
                  </div>
                  {e.reason && <div className="truncate text-11 text-ink-2">{e.reason}</div>}
                </button>
              </li>
            );
          })}
        </ol>
        <section className="flex min-w-0 flex-1 flex-col">
          {selected !== null && version.isLoading && (
            <div className="p-4 text-11 text-ink-3">loading version…</div>
          )}
          {version.isError && (
            <div className="p-4 text-11 text-ink-3">this version could not be loaded</div>
          )}
          {version.data && (
            <>
              <div className="flex-1 overflow-auto p-4">
                {current === null ? (
                  <div className="text-11 text-ink-3">
                    this note no longer exists on disk — restoring recreates it
                  </div>
                ) : unchanged ? (
                  <div className="text-11 text-ink-3">same as the current version</div>
                ) : (
                  <LineDiffView
                    testId="history-diff"
                    oldText={version.data.content}
                    newText={current}
                    legend="- this version · + current"
                  />
                )}
              </div>
              <footer className="flex items-center justify-end gap-2 border-t border-hairline px-4 py-2">
                <Btn
                  variant="primary"
                  size="sm"
                  icon={<Lucide name="rotate-ccw" size={13} />}
                  onClick={() => void restore()}
                  disabled={restoring || unchanged}
                >
                  {restoring ? 'restoring…' : 'restore this version'}
                </Btn>
              </footer>
            </>
          )}
        </section>
      </div>
    </aside>
  );
}
