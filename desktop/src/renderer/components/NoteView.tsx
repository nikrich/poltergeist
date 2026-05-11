import { useEffect, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { useNote } from '../lib/api/hooks';
import { useNoteView } from '../stores/note-view';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { Lucide } from './Lucide';
import { Btn } from './Btn';
import { Eyebrow } from './Eyebrow';
import { SkeletonRows } from './SkeletonRows';
import { PanelError } from './PanelError';

const WIKILINK_RE = /\[\[([^\]]+)\]\]/g;

/** Strip the Obsidian-only `[[wikilink]]` syntax that react-markdown can't render. */
function stripWikilinks(body: string): string {
  return body.replace(WIKILINK_RE, (_, target: string) => {
    const label = target.split('|').pop() ?? target;
    return label.split('/').pop() ?? label;
  });
}

export function NoteView() {
  const path = useNoteView((s) => s.path);
  const close = useNoteView((s) => s.close);
  const note = useNote(path);
  const vaultPath = useSettings((s) => s.vaultPath);

  useEffect(() => {
    if (path === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [path, close]);

  const bodyClean = useMemo(
    () => (note.data ? stripWikilinks(note.data.body) : ''),
    [note.data],
  );

  if (path === null) return null;

  const openInEditor = async () => {
    const target = `${vaultPath}/${path}`;
    const result = await window.gb.shell.openPath(target);
    if (!result.ok) toast.error(result.error);
  };

  return (
    <div
      role="dialog"
      aria-label="note viewer"
      className="fixed inset-0 z-40 flex justify-end bg-[rgba(14,15,18,0.55)] backdrop-blur-sm"
      onClick={close}
    >
      <div
        className="flex h-full w-[820px] max-w-[92vw] flex-col border-l border-hairline bg-paper shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center gap-3 border-b border-hairline px-6 py-4">
          <Lucide name="file-text" size={14} color="var(--ink-2)" />
          <div className="min-w-0 flex-1 leading-[1.2]">
            <div className="truncate text-13 font-medium text-ink-0">
              {note.data?.title ?? path.split('/').pop()}
            </div>
            <div className="truncate font-mono text-10 text-ink-3">{path}</div>
          </div>
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="external-link" size={13} />}
            onClick={openInEditor}
          >
            open in editor
          </Btn>
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="x" size={14} />}
            onClick={close}
            ariaLabel="close"
          />
        </header>

        <div className="flex-1 overflow-y-auto">
          {note.isLoading && (
            <div className="p-6">
              <SkeletonRows count={6} />
            </div>
          )}
          {note.isError && (
            <div className="p-6">
              <PanelError
                message={
                  note.error instanceof Error ? note.error.message : 'failed to load note'
                }
                onRetry={() => note.refetch()}
              />
            </div>
          )}
          {note.data && (
            <article className="gb-prose mx-auto max-w-[680px] px-8 py-8 text-14 leading-[1.65] text-ink-0">
              <FrontmatterStrip fm={note.data.frontmatter} />
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{bodyClean}</ReactMarkdown>
            </article>
          )}
        </div>
      </div>
    </div>
  );
}

function FrontmatterStrip({ fm }: { fm: Record<string, unknown> }) {
  // Show a compact metadata row above the body — only the keys most useful
  // for quick scanning. Full frontmatter is still in the file on disk.
  const candidates: Array<[string, unknown]> = [];
  for (const key of ['date', 'context', 'source', 'type', 'durationSeconds']) {
    if (key in fm) candidates.push([key, fm[key]]);
  }
  if (candidates.length === 0) return null;
  return (
    <div className="mb-6 flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-hairline pb-3">
      {candidates.map(([k, v]) => (
        <div key={k} className="flex items-baseline gap-1">
          <Eyebrow>{k}</Eyebrow>
          <span className="font-mono text-11 text-ink-1">{String(v)}</span>
        </div>
      ))}
    </div>
  );
}
