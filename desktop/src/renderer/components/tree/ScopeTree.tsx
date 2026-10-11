// desktop/src/renderer/components/tree/ScopeTree.tsx
import { Fragment, useEffect, useMemo, useState } from 'react';
import type { FolderRef } from '../../../shared/api-types';
import { Lucide } from '../Lucide';
import { countLeaves, folderKey, groupByContext, isInside, joinPath } from './tree-types';
import type { LeafRowProps, TreeDragCodec, TreeFolderNode, TreeScope } from './tree-types';

export interface ScopeTreeProps<L> {
  scopes: TreeScope<L>[];
  ariaLabel: string;
  codec: TreeDragCodec;
  leafId: (l: L) => string;
  /** Dropping onto a leaf drops into its folder. */
  leafRef: (l: L) => FolderRef;
  renderLeaf: (l: L, row: LeafRowProps, ctx: { depth: number; archived: boolean }) => React.ReactNode;
  selectedFolderKey: string | null;
  /** Absent: clicking a folder name toggles it. */
  onSelectFolder?: (ref: FolderRef) => void;
  onMoveLeaf: (id: string, to: FolderRef) => void;
  onMoveFolder: (from: FolderRef, to: FolderRef) => void;
  onCreateFolder: (ref: FolderRef) => void;
  onRenameFolder: (from: FolderRef, to: FolderRef) => void;
  onDeleteFolder: (ref: FolderRef) => void;
  onUploadFiles?: (files: File[], to: FolderRef) => void;
  onRenameProject?: (ref: { context: string; project: string }, name: string) => void;
  header?: React.ReactNode;
  /** Folder keys / `ctx:<context>` to force-expand. */
  revealKeys?: string[];
  /** Lucide name for bare-context scope rows. */
  rootIcon?: string;
}

const PROJECT_DOTS = ['var(--neon)', 'var(--pill-water-fg)', '#F2C14E', 'var(--pill-oxblood-fg)', '#A9B6FF', 'var(--pill-moss-fg)'];

function validName(v: string | null): string | null {
  if (!v || /[/\\]/.test(v) || v.startsWith('.')) return null;
  return v;
}

// Module scope (not inside ScopeTree) so parent re-renders, e.g. drag hover, don't remount it mid-typing.
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

export function ScopeTree<L>(props: ScopeTreeProps<L>) {
  const { scopes, codec, selectedFolderKey, onSelectFolder, revealKeys, rootIcon = 'inbox' } = props;
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [dropKey, setDropKey] = useState<string | null>(null);
  const [creatingIn, setCreatingIn] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const projectIndexes = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of scopes) if (s.project) m.set(`${s.context}/${s.project}`, m.size);
    return m;
  }, [scopes]);

  const revealSig = revealKeys?.join('|');
  useEffect(() => {
    if (!revealKeys?.length) return;
    setCollapsed((c) => {
      const n = { ...c };
      for (const k of revealKeys) delete n[k];
      return n;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the joined signature, not array identity
  }, [revealSig]);

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
      if (files.length && props.onUploadFiles) return props.onUploadFiles(files, ref);
      const payload = codec.decode(e.dataTransfer.getData(codec.mime));
      if (!payload) return;
      if (payload.kind === 'leaf') return props.onMoveLeaf(payload.id, ref);
      if (isInside(ref, payload.ref)) return;
      const name = payload.ref.path.split('/').pop()!;
      props.onMoveFolder(payload.ref, { ...ref, path: joinPath(ref.path, name) });
    },
  });

  const dropCls = (key: string) =>
    dropKey === key ? 'outline-dashed outline-1 -outline-offset-1 outline-neon bg-neon-mist/40 text-ink-0' : '';
  const baseCls = 'group flex w-full items-center gap-[7px] rounded-md px-1.5 py-[5px] text-left text-13';
  const rowCls = (active: boolean, key: string) =>
    `${baseCls} ${active ? 'bg-neon-mist text-neon' : 'text-ink-1 hover:bg-vellum'} ${dropCls(key)}`;

  const leafRow = (l: L, depth: number, archived: boolean) => {
    const ref = props.leafRef(l);
    const id = props.leafId(l);
    const row: LeafRowProps = {
      draggable: !archived,
      ...dropHandlers(ref, archived),
      onDragStart: (e) => {
        if (archived) return e.preventDefault();
        e.dataTransfer.setData(codec.mime, codec.encodeLeaf(id));
        e.dataTransfer.effectAllowed = 'move';
      },
      className: `${baseCls} ${dropCls(folderKey(ref))}`,
      style: { paddingLeft: 6 + depth * 18 },
    };
    return <Fragment key={id}>{props.renderLeaf(l, row, { depth, archived })}</Fragment>;
  };

  const nameClick = (ref: FolderRef, key: string) => (onSelectFolder ? onSelectFolder(ref) : toggle(key));

  const folderRows = (scope: TreeScope<L>, node: TreeFolderNode<L>, depth: number): React.ReactNode => {
    const ref: FolderRef = { context: scope.context, project: scope.project, path: node.path };
    const key = folderKey(ref);
    const open = !collapsed[key];
    const active = selectedFolderKey === key;
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
            onDragStart={(e) => e.dataTransfer.setData(codec.mime, codec.encodeFolder(ref))}
            {...dropHandlers(ref, scope.archived)}
            className={rowCls(active, key)}
            style={{ paddingLeft: 6 + depth * 18 }}
          >
            <button type="button" aria-label={open ? 'collapse' : 'expand'} onClick={() => toggle(key)} className="w-2.5 text-[9px] text-ink-3">
              {open ? '▾' : '▸'}
            </button>
            <button type="button" onClick={() => nameClick(ref, key)} className="flex min-w-0 flex-1 items-center gap-[7px]">
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
            <span className="ml-auto font-mono text-10 text-ink-3 group-hover:hidden group-focus-within:hidden">{countLeaves(node)}</span>
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
            {node.leaves.map((l) => leafRow(l, depth + 1, scope.archived))}
          </>
        )}
      </div>
    );
  };

  const scopeRows = (scope: TreeScope<L>, i: number) => {
    const ref: FolderRef = { context: scope.context, project: scope.project, path: '' };
    const key = folderKey(ref);
    const open = !collapsed[key];
    const active = selectedFolderKey === key;
    const root: TreeFolderNode<L> = { name: scope.name, path: '', folders: scope.folders, leaves: scope.leaves };
    return (
      <div key={key} className={scope.archived ? 'opacity-50' : ''}>
        {renaming === key && scope.project ? (
          <FolderInput
            raw
            placeholder="project name"
            initial={scope.name}
            onDone={(v) => {
              setRenaming(null);
              if (v && v !== scope.name) props.onRenameProject?.({ context: scope.context, project: scope.project! }, v);
            }}
          />
        ) : (
        <div data-testid={`folder-${key}`} {...dropHandlers(ref, scope.archived)} className={`${rowCls(active, key)} ${scope.project ? 'font-medium text-ink-0' : 'text-ink-2'}`}>
          <button type="button" aria-label={open ? 'collapse' : 'expand'} onClick={() => toggle(key)} className="w-2.5 text-[9px] text-ink-3">
            {open ? '▾' : '▸'}
          </button>
          <button type="button" onClick={() => nameClick(ref, key)} className="flex min-w-0 flex-1 items-center gap-[7px]">
            {scope.project ? (
              <span className="h-[7px] w-[7px] shrink-0 rounded-[2px]" style={{ background: PROJECT_DOTS[i % PROJECT_DOTS.length] }} />
            ) : (
              <Lucide name={rootIcon} size={13} className="shrink-0 opacity-80" />
            )}
            <span className="truncate">{scope.name}</span>
          </button>
          {!scope.archived && (
            <span className="hidden items-center gap-1 group-hover:flex group-focus-within:flex">
              <button type="button" aria-label={`new folder in ${key}`} onClick={() => setCreatingIn(key)} className="text-ink-3 hover:text-neon">
                <Lucide name="folder-plus" size={12} />
              </button>
              {scope.project && props.onRenameProject && (
                <button type="button" aria-label={`rename ${scope.context}/${scope.project}`} onClick={() => setRenaming(key)} className="text-ink-3 hover:text-neon">
                  <Lucide name="pencil" size={12} />
                </button>
              )}
            </span>
          )}
          <span data-testid={`count-${scope.context}/${scope.project ?? '_'}/`} className="ml-auto font-mono text-10 text-ink-3 group-hover:hidden group-focus-within:hidden">
            {countLeaves(root)}
          </span>
        </div>
        )}
        {creatingIn === key && (
          <FolderInput initial="" onDone={(v) => { setCreatingIn(null); if (v) props.onCreateFolder({ ...ref, path: v }); }} />
        )}
        {open && (
          <>
            {scope.folders.map((f) => folderRows(scope, f, 1))}
            {scope.leaves.map((l) => leafRow(l, 1, scope.archived))}
          </>
        )}
      </div>
    );
  };

  return (
    <nav
      className="flex-1 overflow-y-auto px-2 pb-3"
      aria-label={props.ariaLabel}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => e.preventDefault()}
    >
      {props.header}
      {groupByContext(scopes).map((g) => {
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
