// desktop/src/renderer/components/chat/ChatTree.tsx
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChatFolderNode, ChatLocation, ChatScope, ChatTree as ChatTreeData, ChatTreeChat } from '../../../shared/api-types';
import {
  useChatTree,
  useCreateChatFolder,
  useCreateConversation,
  useDeleteChatFolder,
  useDeleteConversation,
  useMoveChat,
  useMoveChatFolder,
  useRenameConversation,
} from '../../lib/api/hooks';
import { useChat } from '../../stores/chat';
import { toast } from '../../stores/toast';
import { Eyebrow } from '../Eyebrow';
import { Lucide } from '../Lucide';
import { SkeletonRows } from '../SkeletonRows';
import { ScopeTree } from '../tree/ScopeTree';
import { countLeaves, folderKey } from '../tree/tree-types';
import type { LeafRowProps, TreeDragCodec, TreeDrop, TreeFolderNode, TreeScope } from '../tree/tree-types';
import { MoveToMenu } from './MoveToMenu';

export const CHAT_DRAG_MIME = 'application/x-gb-chat';

const CHAT_CODEC: TreeDragCodec = {
  mime: CHAT_DRAG_MIME,
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

function toTreeFolder(n: ChatFolderNode): TreeFolderNode<ChatTreeChat> {
  return { name: n.name, path: n.path, folders: n.folders.map(toTreeFolder), leaves: n.chats };
}

function toTreeScope(s: ChatScope): TreeScope<ChatTreeChat> {
  return { context: s.context, project: s.project, name: s.name, archived: s.archived, folders: s.folders.map(toTreeFolder), leaves: s.chats };
}

function findChat(tree: ChatTreeData, id: string): ChatTreeChat | null {
  const inFolders = (nodes: ChatFolderNode[]): ChatTreeChat | null => {
    for (const f of nodes) {
      const hit = f.chats.find((c) => c.id === id) ?? inFolders(f.folders);
      if (hit) return hit;
    }
    return null;
  };
  for (const s of tree.scopes) {
    const hit = s.chats.find((c) => c.id === id) ?? inFolders(s.folders);
    if (hit) return hit;
  }
  return null;
}

/** Keys ScopeTree must expand so the active chat is visible. */
function revealKeysFor(chat: ChatTreeChat | null): string[] {
  if (!chat?.context) return [];
  const base = { context: chat.context, project: chat.project };
  const keys = [`ctx:${chat.context}`, folderKey({ ...base, path: '' })];
  const parts = (chat.folder ?? '').split('/').filter(Boolean);
  parts.forEach((_, i) => keys.push(folderKey({ ...base, path: parts.slice(0, i + 1).join('/') })));
  return keys;
}

type RowChrome = Pick<LeafRowProps, 'draggable' | 'onDragStart' | 'className' | 'style'> & Partial<LeafRowProps>;

interface ChatRowProps {
  chat: ChatTreeChat;
  tree: ChatTreeData;
  row: RowChrome;
  active: boolean;
  onSelect: (id: string | null) => void;
  onMove: (loc: ChatLocation) => void;
}

function ChatRow({ chat, tree, row, active, onSelect, onMove }: ChatRowProps) {
  const rename = useRenameConversation();
  const del = useDeleteConversation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(chat.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const commit = () => {
    const next = draft.trim();
    if (next && next !== chat.title) rename.mutate({ id: chat.id, title: next }, { onError });
    setEditing(false);
  };

  if (editing) {
    return (
      <div style={row.style} className="py-[2px] pr-1">
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === 'Enter') {
              e.preventDefault();
              commit();
            } else if (e.key === 'Escape') {
              e.preventDefault();
              setDraft(chat.title);
              setEditing(false);
            }
          }}
          className="w-full rounded-r6 border border-hairline-2 bg-paper px-2 py-1 text-13 text-ink-0 focus:outline-none"
        />
      </div>
    );
  }

  return (
    <div
      role="button"
      tabIndex={0}
      {...row}
      onClick={() => onSelect(chat.id)}
      onDoubleClick={() => {
        setDraft(chat.title);
        setEditing(true);
      }}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(chat.id);
        }
      }}
      className={`${row.className} cursor-pointer transition-colors duration-[120ms] ${
        active ? 'bg-neon/12 font-medium text-ink-0' : 'font-normal text-ink-1 hover:bg-fog'
      }`}
    >
      <Lucide name="message-square" size={12} className="opacity-60" />
      <span className="min-w-0 flex-1 truncate">{chat.title}</span>
      {chat.unknown_location && (
        <span title="its project or context no longer exists" className="flex-shrink-0 text-ink-3">
          <Lucide name="circle-help" size={11} />
        </span>
      )}
      <MoveToMenu chat={chat} tree={tree} onMove={onMove} />
      <button
        type="button"
        aria-label="delete conversation"
        disabled={del.isPending}
        onClick={(e) => {
          e.stopPropagation();
          del.mutate(chat.id, {
            onSuccess: () => {
              if (active) onSelect(null);
            },
            onError,
          });
        }}
        onDoubleClick={(e) => e.stopPropagation()}
        className="flex h-[18px] w-[18px] flex-shrink-0 items-center justify-center rounded-xs text-ink-3 opacity-0 transition-opacity hover:text-oxblood focus:opacity-100 group-hover:opacity-100 disabled:opacity-50"
      >
        <Lucide name="trash-2" size={12} />
      </button>
    </div>
  );
}

const UNFILED_ROW = 'group flex w-full items-center gap-[7px] rounded-md px-1.5 py-[5px] text-left text-13';

function UnfiledSection({ tree, activeId, onSelect, onMove }: {
  tree: ChatTreeData;
  activeId: string | null;
  onSelect: (id: string | null) => void;
  onMove: (id: string, loc: ChatLocation) => void;
}) {
  const [over, setOver] = useState(false);
  const unfile = { context: null, project: null, folder: null };
  return (
    <div className="mb-1">
      <div
        data-testid="chat-unfiled"
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOver(false);
          const p = CHAT_CODEC.decode(e.dataTransfer.getData(CHAT_DRAG_MIME));
          if (p?.kind === 'leaf') onMove(p.id, unfile);
        }}
        className={`flex items-center gap-[7px] rounded-md px-1.5 py-1 font-mono text-[10.5px] uppercase tracking-[0.1em] text-ink-2 ${
          over ? 'bg-neon-mist/40 text-ink-0 outline-dashed outline-1 -outline-offset-1 outline-neon' : ''
        }`}
      >
        <Lucide name="inbox" size={12} className="opacity-70" />
        <span>unfiled</span>
        <span className="ml-auto text-10 text-ink-3">{tree.unfiled.length}</span>
      </div>
      {tree.unfiled.map((c) => (
        <ChatRow
          key={c.id}
          chat={c}
          tree={tree}
          active={c.id === activeId}
          onSelect={onSelect}
          onMove={(loc) => onMove(c.id, loc)}
          row={{
            draggable: true,
            onDragStart: (e) => {
              e.dataTransfer.setData(CHAT_DRAG_MIME, CHAT_CODEC.encodeLeaf(c.id));
              e.dataTransfer.effectAllowed = 'move';
            },
            className: UNFILED_ROW,
            style: { paddingLeft: 24 },
          }}
        />
      ))}
    </div>
  );
}

export function ChatTree({ activeId, onSelect }: { activeId: string | null; onSelect: (id: string | null) => void }) {
  const tree = useChatTree();
  const create = useCreateConversation();
  const moveChat = useMoveChat();
  const createFolder = useCreateChatFolder();
  const moveFolder = useMoveChatFolder();
  const deleteFolder = useDeleteChatFolder();

  const data = tree.data;
  const scopes = useMemo(() => (data ? data.scopes.map(toTreeScope) : []), [data]);
  const total = useMemo(
    () => (data ? data.unfiled.length + scopes.reduce((n, s) => n + countLeaves(s), 0) : 0),
    [data, scopes],
  );
  const revealKeys = useMemo(
    () => (data && activeId ? revealKeysFor(findChat(data, activeId)) : []),
    [data, activeId],
  );

  // Every manual path (tree drop, unfiled drop, Move-to menu) lands here.
  const move = (id: string, loc: ChatLocation) => {
    useChat.getState().markManualMove(id);
    moveChat.mutate({ id, ...loc }, { onError });
  };

  const newChat = () => create.mutate(undefined, { onSuccess: (conv) => onSelect(conv.id), onError });

  return (
    <aside className="flex w-[240px] flex-shrink-0 flex-col border-r border-hairline bg-vellum">
      <div className="flex items-center justify-between px-[14px] pb-2 pt-[14px]">
        <Eyebrow>conversations</Eyebrow>
        <button
          type="button"
          onClick={newChat}
          aria-label="new chat"
          disabled={create.isPending}
          className="flex h-[22px] w-[22px] items-center justify-center rounded-sm text-ink-2 transition-colors hover:bg-fog hover:text-ink-0 disabled:opacity-50"
        >
          <Lucide name="plus" size={14} />
        </button>
      </div>

      {tree.isLoading && (
        <div className="px-2">
          <SkeletonRows count={4} />
        </div>
      )}
      {tree.isError && (
        <div className="px-3 py-6 text-center font-mono text-10 text-oxblood">failed to load conversations</div>
      )}
      {data && (
        <ScopeTree<ChatTreeChat>
          scopes={scopes}
          ariaLabel="chat tree"
          codec={CHAT_CODEC}
          leafId={(c) => c.id}
          leafRef={(c) => ({ context: c.context!, project: c.project, path: c.folder ?? '' })}
          selectedFolderKey={null}
          rootIcon="message-square"
          revealKeys={revealKeys}
          onMoveLeaf={(id, to) => move(id, { context: to.context, project: to.project, folder: to.path || null })}
          onMoveFolder={(from, to) => moveFolder.mutate({ from, to }, { onError })}
          onCreateFolder={(ref) => createFolder.mutate(ref, { onError })}
          onRenameFolder={(from, to) => moveFolder.mutate({ from, to }, { onError })}
          onDeleteFolder={(ref) => deleteFolder.mutate(ref, { onError })}
          header={
            total === 0 ? (
              <div className="px-3 py-6 text-center font-mono text-10 text-ink-3">no conversations yet</div>
            ) : (
              <UnfiledSection tree={data} activeId={activeId} onSelect={onSelect} onMove={move} />
            )
          }
          renderLeaf={(c, row) => (
            <ChatRow
              chat={c}
              tree={data}
              row={row}
              active={c.id === activeId}
              onSelect={onSelect}
              onMove={(loc) => move(c.id, loc)}
            />
          )}
        />
      )}
    </aside>
  );
}
