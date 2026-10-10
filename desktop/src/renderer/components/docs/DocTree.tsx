// desktop/src/renderer/components/docs/DocTree.tsx
import { useMemo, useState } from 'react';
import type { DocFolderNode, DocScope, DocSummary, FolderRef, LibraryTree } from '../../../shared/api-types';
import type { DocSelection } from '../../stores/docs';
import { Lucide } from '../Lucide';
import { KindChip } from './KindChip';
import { folderKey } from './kinds';
import { countDocs, decodeDrag, DRAG_MIME, encodeDrag, groupByContext, isInside } from './tree-model';

interface Props {
  tree: LibraryTree;
  selection: DocSelection;
  onSelect: (s: DocSelection) => void;
  onMoveDoc: (docId: string, to: FolderRef) => void;
  onMoveFolder: (from: FolderRef, to: FolderRef) => void;
  onUploadFiles: (files: File[], to: FolderRef) => void;
  onCreateFolder: (ref: FolderRef) => void;
  onRenameFolder: (from: FolderRef, to: FolderRef) => void;
  onRenameProject: (ref: { context: string; project: string }, name: string) => void;
  onDeleteFolder: (ref: FolderRef) => void;
}

const PROJECT_DOTS = ['var(--neon)', 'var(--pill-water-fg)', '#F2C14E', 'var(--pill-oxblood-fg)', '#A9B6FF', 'var(--pill-moss-fg)'];

function validName(v: string | null): string | null {
  if (!v || /[/\\]/.test(v) || v.startsWith('.')) return null;
  return v;
}

function joinPath(parent: string, name: string): string {
  return parent ? `${parent}/${name}` : name;
}

// Module scope (not inside DocTree) so parent re-renders, e.g. drag hover, don't remount it mid-typing.
function FolderInput({ initial, onDone, placeholder = 'folder name', raw = false }: { initial: string; onDone: (v: string | null) => void; placeholder?: string; raw?: boolean }) {
  return (
    <input
      autoFocus
      defaultValue={initial}
      placeholder={placeholder}
      className="ml-6 w-[calc(100%-1.5rem)] rounded border border-hairline-2 bg-vellum px-2 py-1 text-12 text-ink-0 outline-none focus:border-neon"
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          const v = (e.target as HTMLInputElement).value.trim() || null;
          onDone(raw ? v : validName(v));
        }
        if (e.key === 'Escape') onDone(null);
      }}
      onBlur={() => onDone(null)}
    />
  );
}

export function DocTree(props: Props) {
  const { tree, selection, onSelect } = props;
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [dropKey, setDropKey] = useState<string | null>(null);
  const [creatingIn, setCreatingIn] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const projectIndexes = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of tree.scopes) if (s.project) m.set(`${s.context}/${s.project}`, m.size);
    return m;
  }, [tree.scopes]);

  const toggle = (k: string) => setCollapsed((c) => ({ ...c, [k]: !c[k] }));

  const dropHandlers = (ref: FolderRef, disabled: boolean) => ({
    onDragOver: (e: React.DragEvent) => {
      if (disabled) return;
      e.preventDefault();
      setDropKey(folderKey(ref));
    },
    onDragLeave: () => setDropKey((k) => (k === folderKey(ref) ? null : k)),
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDropKey(null);
      if (disabled) return;
      const files = Array.from(e.dataTransfer.files ?? []);
      if (files.length) return props.onUploadFiles(files, ref);
      const payload = decodeDrag(e.dataTransfer.getData(DRAG_MIME));
      if (!payload) return;
      if (payload.type === 'doc') return props.onMoveDoc(payload.docId, ref);
      if (isInside(ref, payload.ref)) return;
      const name = payload.ref.path.split('/').pop()!;
      props.onMoveFolder(payload.ref, { ...ref, path: joinPath(ref.path, name) });
    },
  });

  const rowCls = (active: boolean, key: string) =>
    `group flex w-full items-center gap-[7px] rounded-md px-1.5 py-[5px] text-left text-13 ${
      active ? 'bg-neon-mist text-neon' : 'text-ink-1 hover:bg-vellum'
    } ${dropKey === key ? 'outline-dashed outline-1 -outline-offset-1 outline-neon bg-neon-mist/40 text-ink-0' : ''}`;

  const docRow = (d: DocSummary, depth: number, archived: boolean) => {
    const active = selection?.type === 'doc' && selection.docId === d.doc_id;
    return (
      <button
        key={d.doc_id}
        type="button"
        draggable={!archived}
        {...dropHandlers({ context: d.context, project: d.project, path: d.folder }, archived)}
        onDragStart={(e) => {
          if (archived) return e.preventDefault();
          e.dataTransfer.setData(DRAG_MIME, encodeDrag({ type: 'doc', docId: d.doc_id }));
          e.dataTransfer.effectAllowed = 'move';
        }}
        onClick={() => onSelect({ type: 'doc', docId: d.doc_id })}
        className={rowCls(active, folderKey({ context: d.context, project: d.project, path: d.folder }))}
        style={{ paddingLeft: 6 + depth * 18 }}
      >
        <KindChip doc={d} />
        <span className="truncate">{d.title}</span>
        {d.index_status === 'failed' && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-[#F2C14E]" title="indexing failed" />}
      </button>
    );
  };

  const folderRows = (scope: DocScope, node: DocFolderNode, depth: number): React.ReactNode => {
    const ref: FolderRef = { context: scope.context, project: scope.project, path: node.path };
    const key = folderKey(ref);
    const open = !collapsed[key];
    const active = selection?.type === 'folder' && folderKey(selection.ref) === key;
    return (
      <div key={key}>
        {renaming === key ? (
          <FolderInput
            initial={node.name}
            onDone={(v) => {
              setRenaming(null);
              if (v && v !== node.name) {
                const parent = node.path.split('/').slice(0, -1).join('/');
                props.onRenameFolder(ref, { ...ref, path: joinPath(parent, v) });
              }
            }}
          />
        ) : (
          <div
            data-testid={`folder-${key}`}
            draggable={!scope.archived}
            onDragStart={(e) => e.dataTransfer.setData(DRAG_MIME, encodeDrag({ type: 'folder', ref }))}
            {...dropHandlers(ref, scope.archived)}
            className={rowCls(active, key)}
            style={{ paddingLeft: 6 + depth * 18 }}
          >
            <button type="button" aria-label={open ? 'collapse' : 'expand'} onClick={() => toggle(key)} className="w-2.5 text-[9px] text-ink-3">
              {open ? '▾' : '▸'}
            </button>
            <button type="button" onClick={() => onSelect({ type: 'folder', ref })} className="flex min-w-0 flex-1 items-center gap-[7px]">
              <Lucide name="folder" size={13} className="shrink-0 opacity-80" />
              <span className="truncate">{node.name}</span>
            </button>
            {!scope.archived && (
              <span className="hidden items-center gap-1 group-hover:flex group-focus-within:flex">
                <button type="button" aria-label={`new folder in ${key}`} onClick={() => setCreatingIn(key)} className="text-ink-3 hover:text-neon"><Lucide name="folder-plus" size={12} /></button>
                <button type="button" aria-label={`rename ${key}`} onClick={() => setRenaming(key)} className="text-ink-3 hover:text-neon"><Lucide name="pencil" size={12} /></button>
                <button type="button" aria-label={`delete ${key}`} onClick={() => props.onDeleteFolder(ref)} className="text-ink-3 hover:text-oxblood"><Lucide name="trash-2" size={12} /></button>
              </span>
            )}
            <span className="ml-auto font-mono text-10 text-ink-3 group-hover:hidden group-focus-within:hidden">{countDocs(node)}</span>
          </div>
        )}
        {creatingIn === key && (
          <FolderInput
            initial=""
            onDone={(v) => {
              setCreatingIn(null);
              if (v) props.onCreateFolder({ ...ref, path: joinPath(node.path, v) });
            }}
          />
        )}
        {open && (
          <>
            {node.folders.map((f) => folderRows(scope, f, depth + 1))}
            {node.docs.map((d) => docRow(d, depth + 1, scope.archived))}
          </>
        )}
      </div>
    );
  };

  const scopeRows = (scope: DocScope, i: number) => {
    const ref: FolderRef = { context: scope.context, project: scope.project, path: '' };
    const key = folderKey(ref);
    const open = !collapsed[key];
    const active = selection?.type === 'folder' && folderKey(selection.ref) === key;
    const root: DocFolderNode = { name: scope.name, path: '', folders: scope.folders, docs: scope.docs };
    return (
      <div key={key} className={scope.archived ? 'opacity-50' : ''}>
        {renaming === key && scope.project ? (
          <FolderInput
            raw
            placeholder="project name"
            initial={scope.name}
            onDone={(v) => {
              setRenaming(null);
              if (v && v !== scope.name) props.onRenameProject({ context: scope.context, project: scope.project! }, v);
            }}
          />
        ) : (
        <div data-testid={`folder-${key}`} {...dropHandlers(ref, scope.archived)} className={`${rowCls(active, key)} ${scope.project ? 'font-medium text-ink-0' : 'text-ink-2'}`}>
          <button type="button" aria-label={open ? 'collapse' : 'expand'} onClick={() => toggle(key)} className="w-2.5 text-[9px] text-ink-3">
            {open ? '▾' : '▸'}
          </button>
          <button type="button" onClick={() => onSelect({ type: 'folder', ref })} className="flex min-w-0 flex-1 items-center gap-[7px]">
            {scope.project ? (
              <span className="h-[7px] w-[7px] shrink-0 rounded-[2px]" style={{ background: PROJECT_DOTS[i % PROJECT_DOTS.length] }} />
            ) : (
              <Lucide name="inbox" size={13} className="shrink-0 opacity-80" />
            )}
            <span className="truncate">{scope.name}</span>
          </button>
          {!scope.archived && (
            <span className="hidden items-center gap-1 group-hover:flex group-focus-within:flex">
              <button type="button" aria-label={`new folder in ${key}`} onClick={() => setCreatingIn(key)} className="text-ink-3 hover:text-neon">
                <Lucide name="folder-plus" size={12} />
              </button>
              {scope.project && (
                <button type="button" aria-label={`rename ${scope.context}/${scope.project}`} onClick={() => setRenaming(key)} className="text-ink-3 hover:text-neon">
                  <Lucide name="pencil" size={12} />
                </button>
              )}
            </span>
          )}
          <span data-testid={`count-${scope.context}/${scope.project ?? '_'}/`} className="ml-auto font-mono text-10 text-ink-3 group-hover:hidden group-focus-within:hidden">
            {countDocs(root)}
          </span>
        </div>
        )}
        {creatingIn === key && (
          <FolderInput initial="" onDone={(v) => { setCreatingIn(null); if (v) props.onCreateFolder({ ...ref, path: v }); }} />
        )}
        {open && (
          <>
            {scope.folders.map((f) => folderRows(scope, f, 1))}
            {scope.docs.map((d) => docRow(d, 1, scope.archived))}
          </>
        )}
      </div>
    );
  };

  return (
    <nav
      className="flex-1 overflow-y-auto px-2 pb-3"
      aria-label="docs tree"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => e.preventDefault()}
    >
      {tree.attention.length > 0 && (
        <button
          type="button"
          onClick={() => onSelect({ type: 'attention' })}
          className={`mb-1 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-12 ${selection?.type === 'attention' ? 'bg-[rgba(242,193,78,.12)] text-[#F2C14E]' : 'text-[#F2C14E] hover:bg-vellum'}`}
        >
          <Lucide name="triangle-alert" size={13} />
          <span>needs attention</span>
          <span className="ml-auto font-mono text-10">{tree.attention.length}</span>
        </button>
      )}
      {groupByContext(tree.scopes).map((g) => {
        const ctxKey = `ctx:${g.context}`;
        const open = !collapsed[ctxKey];
        return (
          <div key={g.context} className="mt-2">
            <button type="button" onClick={() => toggle(ctxKey)} className="flex w-full items-center gap-[7px] px-1.5 py-1 font-mono text-[10.5px] uppercase tracking-[0.1em] text-ink-2">
              <span className="w-2.5 text-[9px] text-ink-3">{open ? '▾' : '▸'}</span>
              <span>{g.context}</span>
            </button>
            {open && g.scopes.map((s) => scopeRows(s, projectIndexes.get(`${s.context}/${s.project}`) ?? 0))}
          </div>
        );
      })}
    </nav>
  );
}
