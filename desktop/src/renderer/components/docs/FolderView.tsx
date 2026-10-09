import { useMemo, useState } from 'react';
import type { DocFolderNode, DocSummary, FolderRef } from '../../../shared/api-types';
import { useDocs, type UploadGhost } from '../../stores/docs';
import { Lucide } from '../Lucide';
import { KindChip } from './KindChip';
import { formatSize } from './kinds';
import { Thumb } from './Thumb';
import { countDocs, DRAG_MIME, encodeDrag } from './tree-model';

interface Props {
  refKey: string;
  folderRef: FolderRef;
  node: DocFolderNode;
  archived: boolean;
  uploads: UploadGhost[];
  selectedDocId: string | null;
  onSelectDoc: (id: string) => void;
  onOpenDoc: (id: string) => void;
  onOpenFolder: (ref: FolderRef) => void;
  onUploadFiles: (files: File[], ref: FolderRef) => void;
  onNewFolder: (ref: FolderRef) => void;
}

type SortKey = 'name' | 'kind' | 'modified' | 'size';

function relTime(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (Number.isNaN(days)) return '';
  if (days < 1) return 'today';
  if (days < 7) return `${days}d`;
  if (days < 30) return `${Math.floor(days / 7)}w`;
  return `${Math.floor(days / 30)}mo`;
}

function sortDocs(docs: DocSummary[], key: SortKey): DocSummary[] {
  const by: Record<SortKey, (a: DocSummary, b: DocSummary) => number> = {
    name: (a, b) => a.title.localeCompare(b.title),
    kind: (a, b) => a.kind.localeCompare(b.kind) || a.title.localeCompare(b.title),
    modified: (a, b) => b.created.localeCompare(a.created),
    size: (a, b) => b.size - a.size,
  };
  return docs.slice().sort(by[key]);
}

export function FolderView(p: Props) {
  const mode = useDocs((s) => s.viewModes[p.refKey] ?? 'list');
  const setViewMode = useDocs((s) => s.setViewMode);
  const [sort, setSort] = useState<SortKey>('name');
  const [dragOver, setDragOver] = useState(false);
  const docs = useMemo(() => sortDocs(p.node.docs, sort), [p.node.docs, sort]);
  const ghosts = p.uploads.filter((u) => u.key === p.refKey);
  const childRef = (name: string): FolderRef => ({ ...p.folderRef, path: p.folderRef.path ? `${p.folderRef.path}/${name}` : name });
  const dragDoc = (d: DocSummary) => (e: React.DragEvent) => e.dataTransfer.setData(DRAG_MIME, encodeDrag({ type: 'doc', docId: d.doc_id }));

  const empty = !p.node.folders.length && !docs.length && !ghosts.length;

  return (
    <div
      data-testid="folder-view"
      className={`relative flex min-h-0 flex-1 flex-col ${dragOver ? 'bg-neon-mist/30' : ''}`}
      onDragOver={(e) => {
        if (p.archived || !Array.from(e.dataTransfer.types ?? []).includes('Files')) return;
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const files = Array.from(e.dataTransfer.files ?? []);
        if (files.length && !p.archived) p.onUploadFiles(files, p.folderRef);
      }}
    >
      <div className="flex items-center gap-2 border-b border-hairline px-[18px] py-2">
        <div className="flex overflow-hidden rounded-lg border border-hairline-2 font-mono text-11">
          {(['list', 'grid'] as const).map((m) => (
            <button key={m} type="button" onClick={() => setViewMode(p.refKey, m)} className={`px-2.5 py-1 ${mode === m ? 'bg-fog text-ink-0' : 'text-ink-2'}`}>
              {m === 'list' ? '≡ list' : '▦ grid'}
            </button>
          ))}
        </div>
        {mode === 'list' && (
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} className="rounded border border-hairline-2 bg-paper px-2 py-1 font-mono text-11 text-ink-1" aria-label="sort by">
            <option value="name">name</option>
            <option value="kind">kind</option>
            <option value="modified">added</option>
            <option value="size">size</option>
          </select>
        )}
        <span className="flex-1" />
        {!p.archived && (
          <button type="button" onClick={() => p.onNewFolder(p.folderRef)} className="inline-flex items-center gap-1.5 rounded-[7px] border border-hairline-2 px-2.5 py-1 font-mono text-11 text-ink-1 hover:text-ink-0">
            <Lucide name="folder-plus" size={12} /> folder
          </button>
        )}
      </div>

      {empty ? (
        <div className="m-6 grid flex-1 place-items-center rounded-xl border border-dashed border-hairline-3 text-center text-13 text-ink-2">
          <div>
            <div className="mb-1 text-ink-0">drop files here</div>
            they&apos;ll be filed in this folder and indexed for chat & search
          </div>
        </div>
      ) : mode === 'list' ? (
        <div className="overflow-y-auto p-2 text-13">
          {p.node.folders.map((f) => (
            <button key={f.path} type="button" onDoubleClick={() => p.onOpenFolder(childRef(f.name))} onClick={() => p.onOpenFolder(childRef(f.name))} className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-ink-1 hover:bg-vellum">
              <Lucide name="folder" size={13} />
              <span className="truncate">{f.name}</span>
              <span className="ml-auto font-mono text-10 text-ink-3">{countDocs(f)}</span>
            </button>
          ))}
          {docs.map((d) => (
            <button
              key={d.doc_id}
              type="button"
              draggable
              onDragStart={dragDoc(d)}
              onClick={() => p.onSelectDoc(d.doc_id)}
              onDoubleClick={() => p.onOpenDoc(d.doc_id)}
              className={`grid w-full grid-cols-[auto_1fr_70px_60px] items-center gap-2 rounded-md px-2 py-1.5 text-left ${p.selectedDocId === d.doc_id ? 'bg-neon-mist text-ink-0' : 'text-ink-1 hover:bg-vellum'}`}
            >
              <KindChip doc={d} />
              <span className="truncate">{d.title}</span>
              <span className="text-right font-mono text-10 text-ink-3">{relTime(d.created)}</span>
              <span className="text-right font-mono text-10 text-ink-3">{formatSize(d.size)}</span>
            </button>
          ))}
          {ghosts.map((g) => (
            <div key={g.id} className="relative grid grid-cols-[1fr_auto] items-center gap-2 overflow-hidden rounded-md px-2 py-1.5 text-ink-2">
              <span className="truncate">{g.name}</span>
              <span className={`font-mono text-10 ${g.status === 'error' ? 'text-oxblood' : ''}`}>{g.status === 'error' ? g.error : 'uploading…'}</span>
              {g.status === 'uploading' && <span className="absolute inset-x-0 bottom-0 h-[2px] animate-pulse bg-neon shadow-[0_0_10px_var(--neon)]" />}
            </div>
          ))}
        </div>
      ) : (
        <div className="overflow-y-auto">
          {p.node.folders.length > 0 && (
            <div className="flex flex-wrap gap-2 px-[18px] pt-4">
              {p.node.folders.map((f) => (
                <button key={f.path} type="button" onClick={() => p.onOpenFolder(childRef(f.name))} className="flex min-w-[150px] items-center gap-2 rounded-[10px] border border-hairline bg-vellum px-3 py-2 text-12 text-ink-1 hover:border-hairline-3">
                  <Lucide name="folder" size={13} />
                  {f.name}
                  <span className="ml-auto font-mono text-10 text-ink-3">{countDocs(f)}</span>
                </button>
              ))}
            </div>
          )}
          <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-3.5 p-[18px]">
            {docs.map((d) => (
              <button
                key={d.doc_id}
                data-testid="doc-card"
                type="button"
                draggable
                onDragStart={dragDoc(d)}
                onClick={() => p.onSelectDoc(d.doc_id)}
                onDoubleClick={() => p.onOpenDoc(d.doc_id)}
                className={`overflow-hidden rounded-xl border bg-vellum text-left transition-shadow ${p.selectedDocId === d.doc_id ? 'border-neon/50 shadow-[0_0_0_1px_rgba(197,255,61,.25),0_12px_30px_rgba(0,0,0,.4)]' : 'border-hairline hover:border-hairline-3'}`}
              >
                <Thumb doc={d} />
                <div className="flex flex-col gap-1 px-3 py-2.5">
                  <span className="truncate text-12 font-medium text-ink-0">{d.title}</span>
                  <span className="flex items-center gap-1.5 font-mono text-10 text-ink-3">
                    <KindChip doc={d} />
                    {d.pages ? `${d.pages} pp` : formatSize(d.size)} · {relTime(d.created)}
                  </span>
                </div>
              </button>
            ))}
            {ghosts.map((g) => (
              <div key={g.id} className="relative overflow-hidden rounded-xl border border-hairline bg-vellum opacity-85">
                <div className="grid h-[120px] place-items-center bg-[repeating-linear-gradient(135deg,var(--bg-vellum)_0_10px,#181a1f_10px_20px)] font-mono text-11 text-ink-2">
                  {g.status === 'error' ? <span className="px-3 text-center text-oxblood">{g.error}</span> : 'uploading…'}
                </div>
                <div className="px-3 py-2.5 text-12 text-ink-1">{g.name}</div>
                {g.status === 'uploading' && <span className="absolute inset-x-0 bottom-0 h-[3px] animate-pulse bg-neon shadow-[0_0_10px_var(--neon)]" />}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
