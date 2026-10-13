import { useMemo, useState } from 'react';
import type { FolderRef, JotFolderNode, JotListItem, JotScope, JotTree as JotTreeData, JotTreeItem } from '../../shared/api-types';
import { useCreateJotFolder, useDeleteJotFolder, useMoveJot, useMoveJotFolder } from '../lib/api/hooks';
import { toast } from '../stores/toast';
import { Lucide } from './Lucide';
import { ScopeTree } from './tree/ScopeTree';
import { folderKey } from './tree/tree-types';
import type { LeafRowProps, TreeDragCodec, TreeDrop, TreeFolderNode, TreeScope } from './tree/tree-types';

export const JOT_DRAG_MIME = 'application/x-gb-jot';

const JOT_CODEC: TreeDragCodec = {
  mime: JOT_DRAG_MIME,
  encodeLeaf: (id) => JSON.stringify({ kind: 'leaf', id }),
  encodeFolder: (ref) => JSON.stringify({ kind: 'folder', ref }),
  decode: (raw) => {
    try {
      const p = JSON.parse(raw) as TreeDrop;
      if (p?.kind === 'leaf' && typeof p.id === 'string') return p;
      if (p?.kind === 'folder' && p.ref && typeof p.ref.context === 'string') return p;
    } catch {
      /* not ours */
    }
    return null;
  },
};

const onError = (e: Error) => toast.error(e.message);

export function shortDate(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    ...(d.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}),
  });
}

function collect(nodes: JotFolderNode[], out: JotTreeItem[]) {
  for (const f of nodes) {
    collect(f.folders, out);
    out.push(...f.jots);
  }
}

export function flattenJotTree(tree: JotTreeData): JotTreeItem[] {
  const out: JotTreeItem[] = [...tree.inbox, ...tree.unrouted];
  for (const s of tree.scopes) {
    collect(s.folders, out);
    out.push(...s.jots);
  }
  return out.sort((a, b) => b.created.localeCompare(a.created));
}

function toTreeFolder(n: JotFolderNode): TreeFolderNode<JotTreeItem> {
  return { name: n.name, path: n.path, folders: n.folders.map(toTreeFolder), leaves: n.jots };
}

function toTreeScope(s: JotScope): TreeScope<JotTreeItem> {
  return { context: s.context, project: s.project, name: s.name, archived: s.archived, folders: s.folders.map(toTreeFolder), leaves: s.jots };
}

/** Keys ScopeTree must expand so the selected jot is visible. */
function revealKeysFor(j: JotTreeItem | undefined): string[] {
  if (!j?.context || j.routingStatus !== 'routed') return [];
  const base = { context: j.context, project: j.project ?? null };
  const keys = [`ctx:${j.context}`, folderKey({ ...base, path: '' })];
  const parts = (j.folder ?? '').split('/').filter(Boolean);
  parts.forEach((_, i) => keys.push(folderKey({ ...base, path: parts.slice(0, i + 1).join('/') })));
  return keys;
}

type RowChrome = Pick<LeafRowProps, 'draggable' | 'onDragStart' | 'className' | 'style'> & Partial<LeafRowProps>;

function JotRow({ jot, row, active, onSelect }: { jot: JotListItem & { unknownLocation?: boolean }; row: RowChrome; active: boolean; onSelect: (id: string) => void }) {
  return (
    <div
      role="button"
      tabIndex={0}
      {...row}
      onClick={() => onSelect(jot.id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(jot.id);
        }
      }}
      className={`${row.className} cursor-pointer transition-colors duration-[120ms] ${
        active ? 'bg-neon/12 font-medium text-ink-0' : 'font-normal text-ink-1 hover:bg-fog'
      }`}
    >
      <span className="min-w-0 flex-1 truncate">{jot.title}</span>
      {jot.unknownLocation && (
        <span title="its project or context no longer exists" className="flex-shrink-0 text-ink-3">
          <Lucide name="circle-help" size={11} />
        </span>
      )}
      <span className="flex-shrink-0 font-mono text-10 text-ink-3">{shortDate(jot.created)}</span>
    </div>
  );
}

const FLAT_ROW = 'group flex w-full items-center gap-[7px] rounded-md px-1.5 py-[5px] text-left text-13';

function dragRow(id: string, paddingLeft: number): RowChrome {
  return {
    draggable: true,
    onDragStart: (e) => {
      e.dataTransfer.setData(JOT_DRAG_MIME, JOT_CODEC.encodeLeaf(id));
      e.dataTransfer.effectAllowed = 'move';
    },
    className: FLAT_ROW,
    style: { paddingLeft },
  };
}

function Section({ testId, icon, label, items, selectedId, onSelect }: {
  testId: string; icon: string; label: string; items: JotTreeItem[]; selectedId: string | null; onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(true);
  if (items.length === 0) return null;
  return (
    <div className="mb-1">
      <button
        type="button"
        data-testid={testId}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-[7px] rounded-md px-1.5 py-1 font-mono text-[10.5px] uppercase tracking-[0.1em] text-ink-2 hover:bg-fog"
      >
        <Lucide name={open ? 'chevron-down' : 'chevron-right'} size={11} />
        <Lucide name={icon} size={12} className="opacity-70" />
        <span>{label}</span>
        <span className="ml-auto text-10 text-ink-3">{items.length}</span>
      </button>
      {open && items.map((j) => (
        <JotRow key={j.id} jot={j} row={dragRow(j.id, 24)} active={j.id === selectedId} onSelect={onSelect} />
      ))}
    </div>
  );
}

export function JotList({ items, selectedId, onSelect }: { items: JotListItem[]; selectedId: string | null; onSelect: (id: string) => void }) {
  return (
    <div className="flex flex-col px-2 py-2">
      {items.map((j) => (
        <JotRow key={j.id} jot={j} row={dragRow(j.id, 8)} active={j.id === selectedId} onSelect={onSelect} />
      ))}
    </div>
  );
}

export function JotTree({ tree, selectedId, onSelect }: { tree: JotTreeData; selectedId: string | null; onSelect: (id: string) => void }) {
  const moveJot = useMoveJot();
  const createFolder = useCreateJotFolder();
  const moveFolder = useMoveJotFolder();
  const deleteFolder = useDeleteJotFolder();

  const scopes = useMemo(() => tree.scopes.map(toTreeScope), [tree]);
  const revealKeys = useMemo(
    () => (selectedId ? revealKeysFor(flattenJotTree(tree).find((j) => j.id === selectedId)) : []),
    [tree, selectedId],
  );
  const moveFolderTo = (from: FolderRef, to: FolderRef) => moveFolder.mutate({ from, to }, { onError });

  return (
    <ScopeTree<JotTreeItem>
      scopes={scopes}
      ariaLabel="jot tree"
      codec={JOT_CODEC}
      leafId={(j) => j.id}
      leafRef={(j) => ({ context: j.context!, project: j.project ?? null, path: j.folder ?? '' })}
      selectedFolderKey={null}
      rootIcon="notebook-pen"
      revealKeys={revealKeys}
      onMoveLeaf={(id, to) => moveJot.mutate({ id, context: to.context, project: to.project, folder: to.path || null }, { onError })}
      onMoveFolder={moveFolderTo}
      onCreateFolder={(ref) => createFolder.mutate(ref, { onError })}
      onRenameFolder={moveFolderTo}
      onDeleteFolder={(ref) => deleteFolder.mutate(ref, { onError })}
      header={
        <>
          <Section testId="jot-inbox" icon="inbox" label="inbox" items={tree.inbox} selectedId={selectedId} onSelect={onSelect} />
          <Section testId="jot-unrouted" icon="circle-help" label="unrouted" items={tree.unrouted} selectedId={selectedId} onSelect={onSelect} />
        </>
      }
      renderLeaf={(j, row) => <JotRow jot={j} row={row} active={j.id === selectedId} onSelect={onSelect} />}
    />
  );
}
