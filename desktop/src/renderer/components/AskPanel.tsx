import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { useAsk } from '../lib/api/hooks';
import { useNoteView } from '../stores/note-view';
import { Lucide } from './Lucide';
import { Eyebrow } from './Eyebrow';
import { PanelError } from './PanelError';
import type { SearchHit } from '../../shared/api-types';

interface Props {
  open: boolean;
  onClose: () => void;
}

/** Match `[N]` citation markers in the LLM answer. Captures the number. */
const CITATION_RE = /\[(\d+)\]/g;

/** Replace `[1]` markers with markdown links `[1](gb-cite:1)` so react-markdown
 *  renders them as anchors we can intercept and route to the source list. */
function injectCitationLinks(answer: string): string {
  return answer.replace(CITATION_RE, (_, n) => `[\\[${n}\\]](gb-cite:${n})`);
}

export function AskPanel({ open, onClose }: Props) {
  const ask = useAsk();
  const openNote = useNoteView((s) => s.open);
  const inputRef = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState('');

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = q.trim();
    if (!trimmed) return;
    ask.mutate({ q: trimmed, limit: 8 });
  };

  const cite = (n: number) => {
    const source = ask.data?.sources[n - 1];
    if (!source) return;
    openNote(source.path);
    onClose();
  };

  const openSource = (source: SearchHit) => {
    openNote(source.path);
    onClose();
  };

  return (
    <div
      role="dialog"
      aria-label="ask the archive"
      className="fixed inset-0 z-50 flex items-start justify-center bg-[rgba(14,15,18,0.55)] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="mt-[8vh] flex w-[760px] max-w-[92vw] flex-col rounded-r10 border border-hairline bg-vellum shadow-xl"
        onClick={(e) => e.stopPropagation()}
        style={{ maxHeight: '84vh' }}
      >
        <form
          onSubmit={submit}
          className="flex items-center gap-2 border-b border-hairline px-4 py-3"
        >
          <Lucide name="search" size={14} color="var(--ink-2)" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="ask the archive…"
            className="flex-1 border-none bg-transparent text-14 text-ink-0 placeholder:text-ink-3 focus:outline-none"
            disabled={ask.isPending}
          />
          {ask.isPending && (
            <div
              className="h-3 w-3 rounded-full border-2 border-neon border-t-transparent"
              style={{ animation: 'gb-spin 0.9s linear infinite' }}
              aria-label="thinking"
            />
          )}
          <kbd className="rounded-xs bg-fog px-[6px] py-[2px] font-mono text-9 text-ink-2">
            esc
          </kbd>
        </form>

        <div className="flex-1 overflow-y-auto p-5">
          {!ask.data && !ask.isPending && !ask.isError && <EmptyHint />}

          {ask.isPending && <ThinkingState />}

          {ask.isError && (
            <PanelError
              message={
                ask.error instanceof Error ? ask.error.message : 'ask failed'
              }
              onRetry={() => ask.mutate({ q: q.trim(), limit: 8 })}
            />
          )}

          {ask.data && (
            <AnswerView data={ask.data} onCite={cite} onOpenSource={openSource} />
          )}
        </div>
      </div>
    </div>
  );
}

function EmptyHint() {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center text-12 text-ink-3">
      <Lucide name="sparkles" size={14} color="var(--ink-3)" />
      <span>
        ask anything in plain English. ghostbrain searches your vault, reads the
        top notes, and answers with citations.
      </span>
      <span className="font-mono text-10">esc to close</span>
    </div>
  );
}

function ThinkingState() {
  return (
    <div className="flex flex-col items-center gap-3 py-12 text-center">
      <Lucide name="sparkles" size={20} color="var(--neon)" />
      <div className="font-display text-15 text-ink-0">thinking…</div>
      <div className="max-w-[40ch] text-12 text-ink-2">
        searching the vault, reading the top 8 matching notes, and synthesizing
        a cited answer.
      </div>
    </div>
  );
}

interface AnswerViewProps {
  data: { query: string; answer: string; sources: SearchHit[]; error: string | null };
  onCite: (n: number) => void;
  onOpenSource: (s: SearchHit) => void;
}

function AnswerView({ data, onCite, onOpenSource }: AnswerViewProps) {
  const processed = useMemo(() => injectCitationLinks(data.answer), [data.answer]);

  return (
    <div className="flex flex-col gap-6">
      {data.error && (
        <div className="rounded-md border border-oxblood/30 bg-oxblood/10 p-3 text-12 text-oxblood">
          {data.error}
        </div>
      )}

      <article className="gb-prose text-14 leading-[1.65] text-ink-0">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => {
              const match = href?.match(/^gb-cite:(\d+)$/);
              if (match) {
                const n = Number(match[1]);
                return (
                  <button
                    type="button"
                    onClick={() => onCite(n)}
                    className="mx-[1px] inline-flex h-[16px] min-w-[18px] items-center justify-center rounded-xs border border-neon/30 bg-neon/10 px-[3px] align-[1px] font-mono text-9 font-medium text-neon-ink hover:bg-neon/20"
                  >
                    {n}
                  </button>
                );
              }
              return <a href={href}>{children}</a>;
            },
          }}
        >
          {processed}
        </ReactMarkdown>
      </article>

      {data.sources.length > 0 && (
        <section className="border-t border-hairline pt-4">
          <Eyebrow className="mb-2">sources</Eyebrow>
          <div className="flex flex-col gap-1">
            {data.sources.map((s, i) => (
              <SourceRow
                key={s.path + i}
                index={i + 1}
                source={s}
                onOpen={() => onOpenSource(s)}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function SourceRow({
  index,
  source,
  onOpen,
}: {
  index: number;
  source: SearchHit;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-baseline gap-3 rounded-sm px-3 py-2 text-left hover:bg-paper"
    >
      <span className="font-mono text-10 text-ink-2">[{index}]</span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-12 text-ink-0">{source.title}</div>
        <div className="truncate font-mono text-10 text-ink-3">{source.path}</div>
      </div>
      <span className="font-mono text-10 text-ink-3">{source.score.toFixed(2)}</span>
    </button>
  );
}
