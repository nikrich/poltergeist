import { useState } from 'react';
import type { DocSummary } from '../../../shared/api-types';
import { Lucide } from '../Lucide';
import { formatSize, kindLabel } from './kinds';

interface Props {
  doc: DocSummary;
  scopeName: string;
  onRename: (title: string) => void;
  onReindex: () => void;
  onSummarise: () => void;
  onAsk: (question: string) => Promise<boolean>;
  summarising?: boolean;
  onCollapse?: () => void;
}

const Cap = ({ children }: { children: React.ReactNode }) => (
  <span className="font-mono text-10 uppercase tracking-[0.12em] text-ink-3">{children}</span>
);

export function DocInspector({ doc, scopeName, onRename, onReindex, onSummarise, onAsk, summarising, onCollapse }: Props) {
  const [editing, setEditing] = useState(false);
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const canAsk = doc.kind !== 'opaque' && doc.index_status === 'ok';
  const kindLine = `${kindLabel(doc)}${doc.pages ? ` · ${doc.pages} pages` : ''}`;
  const added = new Date(doc.created).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  return (
    <aside className="flex w-[268px] shrink-0 flex-col gap-[18px] border-l border-hairline bg-vellum px-4 py-[18px] text-[12.5px]">
      <div>
        <div className="flex items-center justify-between">
          <Cap>document</Cap>
          {onCollapse && (
            <button type="button" aria-label="collapse inspector" title="collapse inspector (⌘⌥\\)" onClick={onCollapse} className="text-ink-3 hover:text-ink-0">
              <Lucide name="panel-right-close" size={14} />
            </button>
          )}
        </div>
        {editing ? (
          <input
            autoFocus
            defaultValue={doc.title}
            className="mt-1.5 w-full rounded border border-neon bg-paper px-2 py-1 text-16 text-ink-0 outline-none"
            onKeyDown={(e) => {
              const v = (e.target as HTMLInputElement).value.trim();
              if (e.key === 'Enter') {
                setEditing(false);
                if (v && v !== doc.title) onRename(v);
              }
              if (e.key === 'Escape') setEditing(false);
            }}
            onBlur={() => setEditing(false)}
          />
        ) : (
          <h4 className="mt-1.5 text-16 font-medium leading-tight text-ink-0">
            <button type="button" className="cursor-text text-left" title="click to rename" onClick={() => setEditing(true)}>
              {doc.title}
            </button>
          </h4>
        )}
      </div>
      <dl className="grid grid-cols-[70px_1fr] gap-y-1.5 text-12">
        <dt className="font-mono text-[10.5px] text-ink-3">kind</dt>
        <dd className="text-ink-1">{kindLine}</dd>
        <dt className="font-mono text-[10.5px] text-ink-3">size</dt>
        <dd className="text-ink-1">{formatSize(doc.size)}</dd>
        <dt className="font-mono text-[10.5px] text-ink-3">added</dt>
        <dd className="text-ink-1">{added}</dd>
        <dt className="font-mono text-[10.5px] text-ink-3">{doc.project ? 'project' : 'context'}</dt>
        <dd className="text-ink-1">{doc.project ? scopeName : doc.context}</dd>
      </dl>
      {doc.kind !== 'opaque' && (
        <div className="rounded-[10px] border border-[rgba(197,255,61,.18)] bg-gradient-to-b from-[rgba(197,255,61,.06)] to-transparent p-3 leading-normal text-ink-1">
          <span className="mb-1.5 block font-mono text-10 uppercase tracking-[0.12em] text-neon-ink">✦ what poltergeist knows</span>
          {summarising || doc.summary_state === 'pending' ? (
            <span className="animate-pulse text-ink-3">summarising…</span>
          ) : doc.summary && doc.index_status === 'ok' ? (
            <p className="break-words whitespace-pre-line">{doc.summary}</p>
          ) : doc.index_status === 'ok' ? (
            <button type="button" onClick={onSummarise} className="font-mono text-11 text-neon-ink hover:underline">
              summarise
            </button>
          ) : doc.index_status === 'pending' ? (
            <span className="text-ink-3">indexing…</span>
          ) : (
            <span className="text-ink-3">needs indexing first</span>
          )}
        </div>
      )}
      {doc.index_status === 'failed' && (
        <div className="rounded-[10px] border border-[rgba(242,193,78,.3)] bg-[rgba(242,193,78,.06)] p-3 leading-normal text-ink-1">
          Poltergeist couldn&apos;t read this file&apos;s text, so chat and search can&apos;t see it yet.
          <button type="button" onClick={onReindex} className="mt-2 block font-mono text-11 text-[#F2C14E] hover:underline">retry indexing</button>
        </div>
      )}
      <form
        className="mt-auto flex items-center gap-2 rounded-[9px] border border-hairline-2 bg-paper px-2.5 py-2"
        onSubmit={(e) => {
          e.preventDefault();
          const q = question.trim();
          if (!q || asking || !canAsk) return;
          setAsking(true);
          onAsk(q)
            .then((ok) => {
              if (ok) setQuestion('');
            })
            .catch(() => undefined)
            .finally(() => setAsking(false));
        }}
      >
        <input
          name="ask"
          value={question}
          disabled={!canAsk}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={canAsk ? 'ask about this doc…' : 'nothing to ask about yet'}
          className="min-w-0 flex-1 bg-transparent text-12 text-ink-0 outline-none placeholder:text-ink-3 disabled:opacity-60"
        />
        <button type="submit" aria-label="ask" disabled={!canAsk || asking} className="grid h-[22px] w-[22px] place-items-center rounded-md bg-neon font-bold text-[#0E0F12] disabled:opacity-40">↑</button>
      </form>
    </aside>
  );
}
