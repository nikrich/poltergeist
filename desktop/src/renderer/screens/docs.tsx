import { useCallback, useEffect, useRef } from 'react';
import type { AttentionItem, DocSummary, FolderRef } from '../../shared/api-types';
import { AttentionPanel } from '../components/docs/AttentionPanel';
import { DocInspector } from '../components/docs/DocInspector';
import { DocReader } from '../components/docs/DocReader';
import { DocTree } from '../components/docs/DocTree';
import { FolderView } from '../components/docs/FolderView';
import { folderKey, vaultAbs } from '../components/docs/kinds';
import { QuickOpen } from '../components/docs/QuickOpen';
import { findDoc, findFolder } from '../components/docs/tree-model';
import { CLIENT_MAX_BYTES, fileToBase64 } from '../components/docs/upload';
import { Lucide } from '../components/Lucide';
import {
  useAdoptOriginal,
  useCreateConversation,
  useCreateFolder,
  useDeleteDoc,
  useDeleteFolder,
  useDocDetail,
  useLibraryTree,
  useMoveFolder,
  usePatchDoc,
  useReindexDoc,
  useSummariseDoc,
  useRemoveOrphan,
  useUploadDoc,
} from '../lib/api/hooks';
import { useChat } from '../stores/chat';
import { useDocs } from '../stores/docs';
import { useNavigation } from '../stores/navigation';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';

const UPLOAD_CONCURRENCY = 2;
const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function DocsScreen() {
  const tree = useLibraryTree();
  const { selection, select, uploads, addUpload, failUpload, removeUpload, quickOpen, setQuickOpen, treeCollapsed, inspectorCollapsed, toggleTree, toggleInspector, setTreeCollapsed, setInspectorCollapsed } = useDocs();
  const vaultPath = useSettings((s) => s.vaultPath);
  const fileInput = useRef<HTMLInputElement>(null);

  const upload = useUploadDoc();
  const patchDoc = usePatchDoc();
  const deleteDoc = useDeleteDoc();
  const reindex = useReindexDoc();
  const summarise = useSummariseDoc();
  const summarising = useRef(new Set<string>());
  const createConversation = useCreateConversation();
  const createFolder = useCreateFolder();
  const moveFolder = useMoveFolder();
  const deleteFolder = useDeleteFolder();
  const adopt = useAdoptOriginal();
  const removeOrphan = useRemoveOrphan();

  const data = tree.data;
  const selectedDoc = data && selection?.type === 'doc' ? findDoc(data, selection.docId) : null;
  const detail = useDocDetail(selectedDoc?.doc_id ?? null);

  // The folder shown in the main pane: the selected folder, or the selected doc's folder.
  // Default view: the first project, or — in a vault with no projects — the first scope.
  const defaultScope = data?.scopes.find((s) => s.project) ?? data?.scopes[0];
  const folderRef: FolderRef | null =
    selection?.type === 'folder'
      ? selection.ref
      : selectedDoc
        ? { context: selectedDoc.context, project: selectedDoc.project, path: selectedDoc.folder }
        : defaultScope
          ? { context: defaultScope.context, project: defaultScope.project, path: '' }
          : null;

  // A folder delete/move (or doc delete) can leave the selection dangling; fall back to the default view.
  useEffect(() => {
    if (!data || !selection) return;
    if (selection.type === 'folder' && !findFolder(data, selection.ref)) select(null);
    else if (selection.type === 'doc' && !findDoc(data, selection.docId)) select(null);
  }, [data, selection, select]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'p') {
        e.preventDefault();
        setQuickOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setQuickOpen]);

  const hasDocRef = useRef(false);
  hasDocRef.current = !!selectedDoc;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || (e.key !== '\\' && e.code !== 'Backslash')) return;
      const t = e.target as HTMLElement | null;
      if (t && (['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.isContentEditable)) return;
      if (!(e.metaKey || e.ctrlKey) || e.shiftKey) return;
      e.preventDefault();
      if (e.altKey) {
        if (hasDocRef.current) toggleInspector();
      }
      else toggleTree();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [toggleTree, toggleInspector]);

  const uploadFiles = useCallback(
    async (files: File[], to: FolderRef) => {
      const key = folderKey(to);
      const jobs = files.map((file) => {
        const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        addUpload({ id, name: file.name, size: file.size, key });
        return { file, id };
      });
      const one = async ({ file, id }: { file: File; id: string }) => {
          if (file.size > CLIENT_MAX_BYTES) {
            failUpload(id, 'too large (max 20 MB)');
            toast.error(`${file.name} is larger than 20 MB`);
            return;
          }
          try {
            const res = await upload.mutateAsync({
              context: to.context, project: to.project, folder: to.path, name: file.name,
              mime: file.type, content_b64: await fileToBase64(file),
            });
            removeUpload(id);
            if (res.duplicate) toast.info(`${file.name} is already in the library`);
          } catch (e) {
            failUpload(id, errMsg(e));
            toast.error(`upload failed: ${file.name}: ${errMsg(e)}`);
          }
      };
      // Small worker pool: ghosts appear immediately, uploads run UPLOAD_CONCURRENCY at a time.
      let next = 0;
      const worker = async () => {
        for (let job = jobs[next++]; job; job = jobs[next++]) await one(job);
      };
      await Promise.all(Array.from({ length: Math.min(UPLOAD_CONCURRENCY, jobs.length) }, worker));
    },
    [addUpload, failUpload, removeUpload, upload],
  );

  const run = (p: Promise<unknown>, ok?: string) =>
    p.then(() => ok && toast.success(ok)).catch((e: unknown) => toast.error(errMsg(e)));

  const askAbout = async (d: DocSummary, question: string): Promise<boolean> => {
    if (createConversation.isPending) return false;
    try {
      const conv = await createConversation.mutateAsync();
      useChat.getState().queueAsk({
        convId: conv.id,
        text: question,
        attachments: [{ path: d.note_path, title: d.title, kind: d.kind }],
      });
      useChat.getState().setActive(conv.id);
      useNavigation.getState().setActive('chat');
      return true;
    } catch (e) {
      toast.error(errMsg(e));
      return false;
    }
  };

  const scopeName = (ctx: string, proj: string | null) =>
    data?.scopes.find((s) => s.context === ctx && s.project === proj)?.name ?? ctx;
  const crumbFor = (ref: FolderRef) => [ref.context, scopeName(ref.context, ref.project), ...ref.path.split('/').filter(Boolean)].join(' / ');

  const openExternal = async () => {
    if (!selectedDoc) return;
    const r = await window.gb.shell.openPath(vaultAbs(vaultPath, selectedDoc.original_path));
    if (!r.ok) toast.error(r.error ?? 'could not open file');
  };
  const reveal = async () => {
    if (!selectedDoc) return;
    const r = await window.gb.shell.showItemInFolder(vaultAbs(vaultPath, selectedDoc.original_path));
    if (!r.ok) toast.error(r.error ?? 'could not reveal file');
  };

  const node = data && folderRef ? findFolder(data, folderRef) : null;
  const scopeArchived = !!data?.scopes.find((s) => folderRef && s.context === folderRef.context && s.project === folderRef.project)?.archived;

  let main: React.ReactNode;
  if (tree.isLoading) main = <div className="p-8 text-13 text-ink-3">loading library…</div>;
  else if (tree.isError) main = <div className="p-8 text-13 text-oxblood">could not load the library: {errMsg(tree.error)}</div>;
  else if (selection?.type === 'attention' && data) {
    main = (
      <AttentionPanel
        items={data.attention}
        onAdopt={(it: AttentionItem) => run(adopt.mutateAsync({ context: it.context, project: it.project, folder: it.folder, name: it.name }), `added ${it.name}`)}
        onRemoveOrphan={(id) => run(removeOrphan.mutateAsync(id), 'note moved to trash')}
        onReindex={(id) => run(reindex.mutateAsync(id))}
      />
    );
  } else if (selectedDoc) {
    main = (
      <DocReader
        doc={selectedDoc}
        body={detail.data?.body}
        crumb={crumbFor({ context: selectedDoc.context, project: selectedDoc.project, path: selectedDoc.folder })}
        onClose={() => select({ type: 'folder', ref: { context: selectedDoc.context, project: selectedDoc.project, path: selectedDoc.folder } })}
        onOpenExternal={openExternal}
        onReveal={reveal}
        onDelete={() => {
          const back: FolderRef = { context: selectedDoc.context, project: selectedDoc.project, path: selectedDoc.folder };
          run(deleteDoc.mutateAsync(selectedDoc.doc_id).then(() => select({ type: 'folder', ref: back })), 'moved to trash');
        }}
      />
    );
  } else if (folderRef && node) {
    main = (
      <>
        <div className="flex h-[52px] shrink-0 items-center gap-3 border-b border-hairline px-[18px]">
          <span className="truncate font-mono text-[11.5px] text-ink-2">{crumbFor(folderRef)}</span>
        </div>
        <FolderView
          refKey={folderKey(folderRef)}
          folderRef={folderRef}
          node={node}
          archived={scopeArchived}
          uploads={uploads}
          selectedDocId={null}
          onSelectDoc={(id) => select({ type: 'doc', docId: id })}
          onOpenDoc={(id) => select({ type: 'doc', docId: id })}
          onOpenFolder={(ref) => select({ type: 'folder', ref })}
          onUploadFiles={uploadFiles}
          onDismissUpload={removeUpload}
          onNewFolder={(ref) => {
            const taken = new Set(node.folders.map((f) => f.name));
            let name = 'new folder';
            for (let i = 2; taken.has(name); i++) name = `new folder ${i}`;
            void run(createFolder.mutateAsync({ ...ref, path: ref.path ? `${ref.path}/${name}` : name }));
          }}
        />
      </>
    );
  } else {
    main = (
      <div className="grid flex-1 place-items-center text-center text-13 text-ink-2">
        <div>
          <Lucide name="library" size={28} className="mx-auto mb-3 text-ink-3" />
          {data?.scopes.length ? (
            <div className="text-ink-0">folder not found</div>
          ) : (
            <>
              <div className="text-ink-0">your docs library is empty</div>
              create a project in settings, then drop files onto it
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 overflow-hidden bg-paper">
      {treeCollapsed && (
        <div className="flex w-9 shrink-0 flex-col items-center gap-2 border-r border-hairline pt-3.5">
          <button type="button" aria-label="expand docs tree" title="expand docs tree (⌘\\)" onClick={() => setTreeCollapsed(false)} className="text-ink-2 hover:text-ink-0">
            <Lucide name="panel-left-open" size={16} />
          </button>
          <button
            type="button"
            aria-label="upload"
            disabled={!folderRef || scopeArchived}
            onClick={() => fileInput.current?.click()}
            className="text-ink-2 hover:text-ink-0 disabled:opacity-40"
          >
            <Lucide name="upload" size={16} />
          </button>
        </div>
      )}
      <aside className={`${treeCollapsed ? 'hidden' : 'flex'} w-[258px] shrink-0 flex-col border-r border-hairline`}>
        <div className="flex items-center justify-between px-3.5 pb-2.5 pt-4">
          <div className="flex items-center gap-2">
            <button type="button" aria-label="collapse docs tree" title="collapse docs tree (⌘\\)" onClick={() => setTreeCollapsed(true)} className="text-ink-3 hover:text-ink-0">
              <Lucide name="panel-left-close" size={15} />
            </button>
            <b className="text-15 font-medium text-ink-0">docs</b>
          </div>
          <button
            type="button"
            disabled={!folderRef || scopeArchived}
            onClick={() => fileInput.current?.click()}
            className="inline-flex items-center gap-1.5 rounded-[7px] bg-neon px-2.5 py-1.5 font-mono text-11 font-semibold text-[#0E0F12] disabled:opacity-40"
          >
            <Lucide name="plus" size={12} /> upload
          </button>
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = '';
              if (folderRef && files.length) void uploadFiles(files, folderRef);
            }}
          />
        </div>
        <button type="button" onClick={() => setQuickOpen(true)} className="mx-3 mb-2.5 flex items-center justify-between rounded-lg border border-hairline bg-vellum px-2.5 py-[7px] text-[12.5px] text-ink-3">
          find a doc… <kbd className="rounded border border-hairline-2 px-1.5 font-mono text-10 text-ink-2">⌘P</kbd>
        </button>
        {data && (
          <DocTree
            tree={data}
            selection={selection}
            onSelect={select}
            onMoveDoc={(docId, to) => run(patchDoc.mutateAsync({ docId, context: to.context, project: to.project, folder: to.path }))}
            onMoveFolder={(from, to) => run(moveFolder.mutateAsync({ from, to }))}
            onUploadFiles={(files, to) => void uploadFiles(files, to)}
            onCreateFolder={(ref) => run(createFolder.mutateAsync(ref))}
            onRenameFolder={(from, to) => run(moveFolder.mutateAsync({ from, to }))}
            onDeleteFolder={(ref) => run(deleteFolder.mutateAsync(ref))}
          />
        )}
      </aside>
      <section className="flex min-w-0 flex-1 flex-col">{main}</section>
      {selectedDoc && inspectorCollapsed && (
        <div className="flex w-9 shrink-0 flex-col items-center border-l border-hairline bg-vellum pt-3.5">
          <button type="button" aria-label="expand inspector" title="expand inspector (⌘⌥\\)" onClick={() => setInspectorCollapsed(false)} className="text-ink-2 hover:text-ink-0">
            <Lucide name="panel-right-open" size={16} />
          </button>
        </div>
      )}
      {selectedDoc && !inspectorCollapsed && (
        <DocInspector
          onCollapse={() => setInspectorCollapsed(true)}
          doc={selectedDoc}
          scopeName={scopeName(selectedDoc.context, selectedDoc.project)}
          onRename={(title) => run(patchDoc.mutateAsync({ docId: selectedDoc.doc_id, title }))}
          onReindex={() => run(reindex.mutateAsync(selectedDoc.doc_id))}
          summarising={summarise.isPending && summarise.variables === selectedDoc.doc_id}
          onAsk={(q) => askAbout(selectedDoc, q)}
          onSummarise={() => {
            if (summarising.current.has(selectedDoc.doc_id)) return;
            summarising.current.add(selectedDoc.doc_id);
            const id = selectedDoc.doc_id;
            void run(
              summarise
                .mutateAsync(id)
                .then((r) => {
                  if (!r.queued && selectedDoc.summary_state !== 'pending') toast.info('nothing to summarise');
                })
                .finally(() => summarising.current.delete(id)),
            );
          }}
        />
      )}
      <QuickOpen open={quickOpen} onClose={() => setQuickOpen(false)} onPick={(docId) => select({ type: 'doc', docId })} />
    </div>
  );
}
