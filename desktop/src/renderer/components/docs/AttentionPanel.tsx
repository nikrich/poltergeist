import type { AttentionItem } from '../../../shared/api-types';
import { Lucide } from '../Lucide';

interface Props {
  items: AttentionItem[];
  onAdopt: (item: AttentionItem) => void;
  onRemoveOrphan: (docId: string) => void;
  onReindex: (docId: string) => void;
}

const COPY: Record<AttentionItem['kind'], { title: string; hint: string; action: string }> = {
  unclaimed_original: { title: 'not in the library yet', hint: 'added outside the app (Finder, sync)', action: 'add to library' },
  orphan_note: { title: 'original file is missing', hint: 'the note remains but its file is gone', action: 'remove note' },
  index_failed: { title: 'indexing failed', hint: "chat and search can't see its text", action: 'retry' },
};

export function AttentionPanel({ items, onAdopt, onRemoveOrphan, onReindex }: Props) {
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="mb-1 text-20 font-medium text-ink-0">needs attention</h2>
      <p className="mb-5 text-13 text-ink-2">files and notes that are out of step with each other. Nothing here was deleted.</p>
      <div className="flex flex-col gap-2">
        {items.map((it) => {
          const c = COPY[it.kind];
          const where = [it.context, it.project, it.folder].filter(Boolean).join(' / ');
          const act = () => {
            if (it.kind === 'unclaimed_original') onAdopt(it);
            else if (it.kind === 'orphan_note') onRemoveOrphan(it.doc_id!);
            else onReindex(it.doc_id!);
          };
          return (
            <div key={`${it.kind}:${where}:${it.name}`} className="flex items-center gap-3 rounded-[10px] border border-hairline bg-vellum px-4 py-3">
              <Lucide name="triangle-alert" size={14} className="text-[#F2C14E]" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-13 text-ink-0">{it.name}</div>
                <div className="font-mono text-10 text-ink-3">{c.title} · {where} · {c.hint}</div>
              </div>
              <button type="button" onClick={act} className="rounded-[7px] border border-hairline-2 px-2.5 py-1 font-mono text-11 text-ink-1 hover:border-neon hover:text-neon">{c.action}</button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
