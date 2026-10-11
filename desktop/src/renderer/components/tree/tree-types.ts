// desktop/src/renderer/components/tree/tree-types.ts
import type { FolderRef } from '../../../shared/api-types';

export interface TreeFolderNode<L> { name: string; path: string; folders: TreeFolderNode<L>[]; leaves: L[] }
export interface TreeScope<L> {
  context: string; project: string | null; name: string; archived: boolean;
  folders: TreeFolderNode<L>[]; leaves: L[];
}
export type TreeDrop = { kind: 'leaf'; id: string } | { kind: 'folder'; ref: FolderRef };
export interface TreeDragCodec {
  mime: string;
  encodeLeaf: (id: string) => string;
  encodeFolder: (ref: FolderRef) => string;
  decode: (raw: string) => TreeDrop | null;
}
/** Props ScopeTree hands a leaf row so the caller renders its own element (the caller supplies `key`-free spreading; ScopeTree keys the wrapper). */
export interface LeafRowProps {
  draggable: boolean;
  onDragStart: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
  /** Shared layout + drop-highlight classes only; the caller adds active/inactive colours. */
  className: string;
  style: React.CSSProperties;
}

export function folderKey(ref: FolderRef): string {
  return `${ref.context}/${ref.project ?? '_'}/${ref.path}`;
}

export function joinPath(parent: string, name: string): string {
  return parent ? `${parent}/${name}` : name;
}

export function isInside(child: FolderRef, parent: FolderRef): boolean {
  if (child.context !== parent.context || child.project !== parent.project) return false;
  return child.path === parent.path || child.path.startsWith(`${parent.path}/`);
}

export function countLeaves<L>(n: { leaves: L[]; folders: TreeFolderNode<L>[] }): number {
  return n.leaves.length + n.folders.reduce((c, f) => c + countLeaves(f), 0);
}

export function groupByContext<S extends { context: string; project: string | null }>(scopes: S[]): Array<{ context: string; scopes: S[] }> {
  const out: Array<{ context: string; scopes: S[] }> = [];
  for (const s of scopes) {
    let g = out.find((x) => x.context === s.context);
    if (!g) out.push((g = { context: s.context, scopes: [] }));
    g.scopes.push(s);
  }
  for (const g of out) g.scopes.sort((a, b) => (a.project === null ? -1 : b.project === null ? 1 : 0));
  return out;
}
