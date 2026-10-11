// desktop/src/renderer/components/docs/tree-model.ts
import type { DocFolderNode, DocScope, DocSummary, FolderRef, LibraryTree } from '../../../shared/api-types';

export const DRAG_MIME = 'application/x-gb-library';

export type DragPayload = { type: 'doc'; docId: string } | { type: 'folder'; ref: FolderRef };

export function encodeDrag(p: DragPayload): string {
  return JSON.stringify(p);
}

export function decodeDrag(raw: string): DragPayload | null {
  try {
    const p = JSON.parse(raw) as DragPayload;
    if (p?.type === 'doc' && typeof p.docId === 'string') return p;
    if (p?.type === 'folder' && typeof p.ref?.context === 'string' && typeof p.ref.path === 'string') return p;
  } catch {
    // not ours
  }
  return null;
}

export function countDocs(node: { docs: unknown[]; folders: DocFolderNode[] }): number {
  return node.docs.length + node.folders.reduce((n, f) => n + countDocs(f), 0);
}

function scopeOf(tree: LibraryTree, ref: Pick<FolderRef, 'context' | 'project'>): DocScope | undefined {
  return tree.scopes.find((s) => s.context === ref.context && s.project === ref.project);
}

export function findFolder(tree: LibraryTree, ref: FolderRef): DocFolderNode | null {
  const scope = scopeOf(tree, ref);
  if (!scope) return null;
  let node: DocFolderNode = { name: scope.name, path: '', folders: scope.folders, docs: scope.docs };
  if (!ref.path) return node;
  for (const part of ref.path.split('/')) {
    const next = node.folders.find((f) => f.name === part);
    if (!next) return null;
    node = next;
  }
  return node;
}

export function findDoc(tree: LibraryTree, docId: string): DocSummary | null {
  const walk = (n: { docs: DocSummary[]; folders: DocFolderNode[] }): DocSummary | null =>
    n.docs.find((d) => d.doc_id === docId) ?? n.folders.map(walk).find(Boolean) ?? null;
  for (const s of tree.scopes) {
    const hit = walk(s);
    if (hit) return hit;
  }
  return null;
}

export { groupByContext, isInside } from '../tree/tree-types';
