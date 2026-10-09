import { useEffect } from 'react';
import type { DocSummary } from '../../../shared/api-types';
import { Lucide } from '../Lucide';
import { MarkdownBody } from '../MarkdownBody';
import { docUrl } from './kinds';
import { PdfViewer } from './PdfViewer';

interface Props {
  doc: DocSummary;
  body: string | undefined;
  crumb: string;
  onClose: () => void;
  onOpenExternal: () => void;
  onReveal: () => void;
  onDelete: () => void;
}

function StatusPill({ status }: { status: DocSummary['index_status'] }) {
  if (status === 'pending') {
    return <span className="inline-flex items-center gap-1.5 rounded-full bg-hairline px-2.5 py-[3px] font-mono text-[10.5px] text-ink-3">indexing…</span>;
  }
  if (status === 'failed') {
    return <span className="inline-flex items-center gap-1.5 rounded-full bg-[rgba(242,193,78,.12)] px-2.5 py-[3px] font-mono text-[10.5px] text-[#F2C14E]">index failed</span>;
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-neon-mist px-2.5 py-[3px] font-mono text-[10.5px] text-neon-ink">
      <span className="h-1.5 w-1.5 rounded-full bg-neon shadow-[0_0_8px_var(--neon)]" />
      indexed
    </span>
  );
}

function Viewer({ doc, body, onOpenExternal }: Pick<Props, 'doc' | 'body' | 'onOpenExternal'>) {
  if (doc.kind === 'pdf') return <PdfViewer url={docUrl(doc.original_path, doc.doc_id)} />;
  if (doc.kind === 'image') {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-6">
        <img src={docUrl(doc.original_path, doc.doc_id)} alt={doc.title} className="max-h-full max-w-full rounded shadow-[0_20px_50px_rgba(0,0,0,.55)]" />
      </div>
    );
  }
  if (doc.kind === 'opaque') {
    return (
      <div className="grid flex-1 place-items-center">
        <div className="rounded-xl border border-hairline-2 bg-vellum px-8 py-6 text-center text-13 text-ink-1">
          <div className="mb-3">no in-app preview for this file type</div>
          <button type="button" onClick={onOpenExternal} className="rounded-[7px] bg-neon px-3 py-1.5 font-mono text-11 font-semibold text-[#0E0F12]">open in default app ↗</button>
        </div>
      </div>
    );
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-10 py-8">
      {body === undefined ? <div className="text-13 text-ink-3">loading…</div> : <MarkdownBody className="mx-auto max-w-[760px]">{body || '_no extractable text_'}</MarkdownBody>}
    </div>
  );
}

export function DocReader({ doc, body, crumb, onClose, onOpenExternal, onReveal, onDelete }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      const t = e.target;
      if (t instanceof HTMLElement && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return;
      onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-[#0A0B0D]">
      <div className="flex h-[52px] shrink-0 items-center gap-3 border-b border-hairline bg-paper px-[18px]">
        <button type="button" aria-label="back to folder" onClick={onClose} className="text-ink-3 hover:text-ink-0"><Lucide name="arrow-left" size={14} /></button>
        <span className="truncate font-mono text-[11.5px] text-ink-2">
          {crumb} / <em className="not-italic text-ink-0">{doc.original}</em>
        </span>
        <span className="flex-1" />
        <StatusPill status={doc.index_status} />
        <button type="button" onClick={onOpenExternal} className="rounded-[7px] border border-hairline-2 px-2.5 py-1 font-mono text-11 text-ink-1 hover:text-ink-0">open in ↗</button>
        <button type="button" aria-label="reveal in folder" onClick={onReveal} className="rounded-[7px] border border-hairline-2 p-1.5 text-ink-1 hover:text-ink-0"><Lucide name="folder-open" size={13} /></button>
        <button type="button" aria-label="move to trash" onClick={onDelete} className="rounded-[7px] border border-hairline-2 p-1.5 text-ink-1 hover:text-oxblood"><Lucide name="trash-2" size={13} /></button>
      </div>
      <Viewer doc={doc} body={body} onOpenExternal={onOpenExternal} />
    </div>
  );
}
