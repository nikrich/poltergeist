import { useState } from 'react';
import type { DocSummary } from '../../../shared/api-types';
import { formatSize, kindLabel } from './kinds';

interface Props {
  doc: DocSummary;
  scopeName: string;
  onRename: (title: string) => void;
  onReindex: () => void;
}

const Cap = ({ children }: { children: React.ReactNode }) => (
  <span className="font-mono text-10 uppercase tracking-[0.12em] text-ink-3">{children}</span>
);

export function DocInspector({ doc, scopeName, onRename, onReindex }: Props) {
  const [editing, setEditing] = useState(false);
  const kindLine = `${kindLabel(doc)}${doc.pages ? ` · ${doc.pages} pages` : ''}`;
  const added = new Date(doc.created).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  return (
    <aside className="flex w-[268px] shrink-0 flex-col gap-[18px] border-l border-hairline bg-vellum px-4 py-[18px] text-[12.5px]">
      <div>
        <Cap>document</Cap>
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
      {doc.index_status === 'failed' && (
        <div className="rounded-[10px] border border-[rgba(242,193,78,.3)] bg-[rgba(242,193,78,.06)] p-3 leading-normal text-ink-1">
          Poltergeist couldn&apos;t read this file&apos;s text, so chat and search can&apos;t see it yet.
          <button type="button" onClick={onReindex} className="mt-2 block font-mono text-11 text-[#F2C14E] hover:underline">retry indexing</button>
        </div>
      )}
    </aside>
  );
}
