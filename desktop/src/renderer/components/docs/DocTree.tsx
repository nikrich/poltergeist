// desktop/src/renderer/components/docs/DocTree.tsx
import { useMemo } from 'react';
import type { DocFolderNode, DocScope, DocSummary, FolderRef, LibraryTree } from '../../../shared/api-types';
import type { DocSelection } from '../../stores/docs';
import { Lucide } from '../Lucide';
import { ScopeTree } from '../tree/ScopeTree';
import { folderKey } from '../tree/tree-types';
import type { TreeDragCodec, TreeFolderNode, TreeScope } from '../tree/tree-types';
import { KindChip } from './KindChip';
import { decodeDrag, DRAG_MIME, encodeDrag } from './tree-model';

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

const DOC_CODEC: TreeDragCodec = {
  mime: DRAG_MIME,
  encodeLeaf: (docId) => encodeDrag({ type: 'doc', docId }),
  encodeFolder: (ref) => encodeDrag({ type: 'folder', ref }),
  decode: (raw) => {
    const p = decodeDrag(raw);
    if (!p) return null;
    return p.type === 'doc' ? { kind: 'leaf', id: p.docId } : { kind: 'folder', ref: p.ref };
  },
};

function toTreeFolder(n: DocFolderNode): TreeFolderNode<DocSummary> {
  return { name: n.name, path: n.path, folders: n.folders.map(toTreeFolder), leaves: n.docs };
}

function toTreeScope(s: DocScope): TreeScope<DocSummary> {
  return { context: s.context, project: s.project, name: s.name, archived: s.archived, folders: s.folders.map(toTreeFolder), leaves: s.docs };
}

export function DocTree(props: Props) {
  const { tree, selection, onSelect } = props;
  const scopes = useMemo(() => tree.scopes.map(toTreeScope), [tree.scopes]);
  return (
    <ScopeTree<DocSummary>
      scopes={scopes}
      ariaLabel="docs tree"
      codec={DOC_CODEC}
      leafId={(d) => d.doc_id}
      leafRef={(d) => ({ context: d.context, project: d.project, path: d.folder })}
      selectedFolderKey={selection?.type === 'folder' ? folderKey(selection.ref) : null}
      onSelectFolder={(ref) => onSelect({ type: 'folder', ref })}
      onMoveLeaf={props.onMoveDoc}
      onMoveFolder={props.onMoveFolder}
      onCreateFolder={props.onCreateFolder}
      onRenameFolder={props.onRenameFolder}
      onDeleteFolder={props.onDeleteFolder}
      onUploadFiles={props.onUploadFiles}
      onRenameProject={props.onRenameProject}
      header={
        tree.attention.length > 0 ? (
          <button
            type="button"
            onClick={() => onSelect({ type: 'attention' })}
            className={`mb-1 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-12 ${selection?.type === 'attention' ? 'bg-[rgba(242,193,78,.12)] text-[#F2C14E]' : 'text-[#F2C14E] hover:bg-vellum'}`}
          >
            <Lucide name="triangle-alert" size={13} />
            <span>needs attention</span>
            <span className="ml-auto font-mono text-10">{tree.attention.length}</span>
          </button>
        ) : null
      }
      renderLeaf={(d, row) => {
        const active = selection?.type === 'doc' && selection.docId === d.doc_id;
        return (
          <button
            type="button"
            {...row}
            onClick={() => onSelect({ type: 'doc', docId: d.doc_id })}
            className={`${row.className} ${active ? 'bg-neon-mist text-neon' : 'text-ink-1 hover:bg-vellum'}`}
          >
            <KindChip doc={d} />
            <span className="truncate">{d.title}</span>
            {d.index_status === 'failed' && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-[#F2C14E]" title="indexing failed" />}
          </button>
        );
      }}
    />
  );
}
