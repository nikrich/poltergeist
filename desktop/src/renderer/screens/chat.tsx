import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Eyebrow } from '../components/Eyebrow';
import { TopBar } from '../components/TopBar';
import { MarkdownBody } from '../components/MarkdownBody';
import { SkeletonRows } from '../components/SkeletonRows';
import { PanelError } from '../components/PanelError';
import {
  useConversations,
  useConversation,
  useCreateConversation,
  useRenameConversation,
  useDeleteConversation,
} from '../lib/api/hooks';
import { useChat } from '../stores/chat';
import type { StreamState, TurnError } from '../stores/chat';
import type {
  ChatMessage,
  ChatToolUse,
  ConversationSummary,
} from '../../shared/api-types';

export function ChatScreen() {
  const qc = useQueryClient();
  const activeId = useChat((s) => s.activeId);
  const setActive = useChat((s) => s.setActive);
  const streams = useChat((s) => s.streams);
  const errors = useChat((s) => s.errors);
  const beginStream = useChat((s) => s.beginStream);
  const applyEvent = useChat((s) => s.applyEvent);
  const endStream = useChat((s) => s.endStream);

  const conversations = useConversations();
  const conversation = useConversation(activeId);

  const stream = activeId ? streams[activeId] : undefined;
  const error = activeId ? errors[activeId] : undefined;

  // Subscribe to streaming events relayed from the main process. One listener
  // for all conversations — the payload carries its own convId.
  useEffect(() => {
    return window.gb.on('chat:event', ({ convId, event }) => {
      applyEvent(convId, event);
      if (event.type === 'done' || event.type === 'error') {
        // Known cosmetic flicker: on done the optimistic bubble clears before
        // the ['chat'] prefix-invalidation refetch lands (sub-100ms locally) —
        // accepted for v1.
        qc.invalidateQueries({ queryKey: ['chat'] });
      }
    });
  }, [applyEvent, qc]);

  // Auto-select the most recent conversation on mount when nothing is active.
  // The list comes back newest-first from the sidecar, so the head is freshest.
  useEffect(() => {
    if (activeId !== null) return;
    const first = conversations.data?.[0];
    if (first) setActive(first.id);
  }, [activeId, conversations.data, setActive]);

  const sendMessage = (text: string) => {
    if (!activeId) return;
    beginStream(activeId, text);
    void window.gb.chat.send(activeId, text).then((res) => {
      if (!res.ok) {
        applyEvent(activeId, { type: 'error', message: res.error });
      }
      // Finalizer: covers user-stop / relay teardown where no terminal event
      // arrives. No-op when done/error already cleared the stream. Same
      // cosmetic flicker window as the done|error path above applies here.
      endStream(activeId);
      qc.invalidateQueries({ queryKey: ['chat'] });
    });
  };

  return (
    <div className="flex flex-1 overflow-hidden bg-paper">
      <ConversationList
        conversations={conversations.data ?? []}
        isLoading={conversations.isLoading}
        activeId={activeId}
        onSelect={setActive}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          title="chat"
          subtitle={conversation.data?.title ?? 'with poltergeist'}
        />

        {activeId === null ? (
          <NoConversation />
        ) : (
          <>
            <Thread
              conversation={conversation}
              stream={stream}
              error={error}
              onStop={() => window.gb.chat.stop(activeId)}
              onRetry={sendMessage}
            />
            <Composer
              disabled={!!stream}
              onSend={sendMessage}
            />
          </>
        )}
      </div>
    </div>
  );
}

// ── Conversation list ──────────────────────────────────────────────────────

interface ConversationListProps {
  conversations: ConversationSummary[];
  isLoading: boolean;
  activeId: string | null;
  onSelect: (id: string | null) => void;
}

function ConversationList({
  conversations,
  isLoading,
  activeId,
  onSelect,
}: ConversationListProps) {
  const create = useCreateConversation();

  const newChat = () => {
    create.mutate(undefined, {
      onSuccess: (conv) => onSelect(conv.id),
    });
  };

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

      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {isLoading && <SkeletonRows count={4} />}
        {!isLoading && conversations.length === 0 && (
          <div className="px-3 py-6 text-center font-mono text-10 text-ink-3">
            no conversations yet
          </div>
        )}
        {conversations.map((c) => (
          <ConversationRow
            key={c.id}
            conversation={c}
            active={c.id === activeId}
            onSelect={() => onSelect(c.id)}
            onDeleted={() => {
              if (c.id === activeId) onSelect(null);
            }}
          />
        ))}
      </div>
    </aside>
  );
}

interface ConversationRowProps {
  conversation: ConversationSummary;
  active: boolean;
  onSelect: () => void;
  onDeleted: () => void;
}

function ConversationRow({
  conversation,
  active,
  onSelect,
  onDeleted,
}: ConversationRowProps) {
  const rename = useRenameConversation();
  const del = useDeleteConversation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conversation.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const commit = () => {
    const next = draft.trim();
    if (next && next !== conversation.title) {
      rename.mutate({ id: conversation.id, title: next });
    }
    setEditing(false);
  };

  const remove = (e: React.MouseEvent) => {
    e.stopPropagation();
    del.mutate(conversation.id, { onSuccess: onDeleted });
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            commit();
          } else if (e.key === 'Escape') {
            e.preventDefault();
            setDraft(conversation.title);
            setEditing(false);
          }
        }}
        className="w-full rounded-r6 border border-hairline-2 bg-paper px-[10px] py-[7px] text-13 text-ink-0 focus:outline-none"
      />
    );
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onDoubleClick={() => {
        setDraft(conversation.title);
        setEditing(true);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect();
        }
      }}
      className={`group flex w-full cursor-pointer items-center gap-2 rounded-r6 px-[10px] py-[7px] text-left text-13 transition-colors duration-[120ms] ${
        active ? 'bg-neon/12 font-medium text-ink-0' : 'font-normal text-ink-1 hover:bg-fog'
      }`}
    >
      <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap">
        {conversation.title}
      </span>
      <button
        type="button"
        onClick={remove}
        aria-label="delete conversation"
        disabled={del.isPending}
        className="flex h-[18px] w-[18px] flex-shrink-0 items-center justify-center rounded-xs text-ink-3 opacity-0 transition-opacity hover:text-oxblood group-hover:opacity-100 disabled:opacity-50"
      >
        <Lucide name="trash-2" size={12} />
      </button>
    </div>
  );
}

// ── Thread ─────────────────────────────────────────────────────────────────

interface ThreadProps {
  conversation: ReturnType<typeof useConversation>;
  stream: StreamState | undefined;
  error: TurnError | undefined;
  onStop: () => void;
  /** Re-sends the failed turn's user text through the normal send path —
   *  beginStream clears the error. Standard resend semantics: the user
   *  message appears again in the transcript. */
  onRetry: (text: string) => void;
}

function Thread({ conversation, stream, error, onStop, onRetry }: ThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const messages = conversation.data?.messages ?? [];

  // Auto-scroll to the newest content as messages land and the stream grows.
  useLayoutEffect(() => {
    bottomRef.current?.scrollIntoView?.({ block: 'end' });
  }, [messages.length, stream?.text, stream?.tools.length, error]);

  const empty =
    !conversation.isLoading &&
    !conversation.isError &&
    messages.length === 0 &&
    !stream &&
    !error;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-[760px] flex-col gap-5 px-6 py-6">
        {conversation.isLoading && <SkeletonRows count={3} height={48} />}

        {conversation.isError && (
          <PanelError
            message={
              conversation.error instanceof Error
                ? conversation.error.message
                : 'failed to load conversation'
            }
            onRetry={() => conversation.refetch()}
          />
        )}

        {empty && <EmptyThreadHint />}

        {messages.map((m, i) => (
          <Message key={i} message={m} />
        ))}

        {stream && <StreamingTurn stream={stream} onStop={onStop} />}

        {error && (
          <div className="flex items-center gap-3 rounded-md border border-oxblood/30 bg-oxblood/10 p-3 text-12 text-oxblood">
            <span className="min-w-0 flex-1">{error.message}</span>
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="rotate-ccw" size={12} />}
              onClick={() => onRetry(error.userText)}
            >
              retry
            </Btn>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function Message({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-r10 border border-hairline bg-vellum px-[14px] py-[10px] text-14 leading-[1.5] text-ink-0">
          {message.text}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {message.tools && message.tools.length > 0 && (
        <ToolChips tools={message.tools} />
      )}
      <MarkdownBody className="text-14 leading-[1.65] text-ink-0">
        {message.text}
      </MarkdownBody>
      {message.interrupted && (
        <div className="font-mono text-10 text-ink-3">⏱ turn was interrupted</div>
      )}
    </div>
  );
}

function StreamingTurn({ stream, onStop }: { stream: StreamState; onStop: () => void }) {
  return (
    <>
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-r10 border border-hairline bg-vellum px-[14px] py-[10px] text-14 leading-[1.5] text-ink-0">
          {stream.userText}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {stream.tools.length > 0 && <ToolChips tools={stream.tools} />}
        {stream.text ? (
          <MarkdownBody className="text-14 leading-[1.65] text-ink-0">
            {stream.text}
          </MarkdownBody>
        ) : (
          <div className="flex items-center gap-2 text-12 text-ink-2">
            <Lucide name="sparkles" size={13} color="var(--neon)" />
            poltergeist is thinking…
          </div>
        )}
        <div>
          <Btn
            variant="danger"
            size="sm"
            icon={<Lucide name="square" size={10} />}
            onClick={onStop}
          >
            stop
          </Btn>
        </div>
      </div>
    </>
  );
}

function ToolChips({ tools }: { tools: ChatToolUse[] }) {
  return (
    <div className="flex flex-wrap gap-[6px]">
      {tools.map((t, i) => (
        <span
          key={i}
          className="inline-flex items-center gap-1 rounded-xs bg-fog px-2 py-[2px] font-mono text-10 text-ink-2"
        >
          <Lucide name="wrench" size={9} color="var(--ink-3)" />
          {t.summary}
        </span>
      ))}
    </div>
  );
}

function EmptyThreadHint() {
  return (
    <div className="flex flex-col items-center gap-2 py-16 text-center text-12 text-ink-3">
      <Lucide name="sparkles" size={16} color="var(--ink-3)" />
      <span className="max-w-[40ch]">
        chat with poltergeist about your vault. it remembers this conversation
        and can search your notes as you go.
      </span>
    </div>
  );
}

function NoConversation() {
  const create = useCreateConversation();
  const setActive = useChat((s) => s.setActive);
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
      <Lucide name="message-circle" size={22} color="var(--ink-3)" />
      <div className="max-w-[36ch] text-13 text-ink-2">
        no conversation selected. start a new one to chat with poltergeist.
      </div>
      <Btn
        variant="primary"
        size="md"
        icon={<Lucide name="plus" size={14} color="#0E0F12" />}
        disabled={create.isPending}
        onClick={() =>
          create.mutate(undefined, { onSuccess: (conv) => setActive(conv.id) })
        }
      >
        new chat
      </Btn>
    </div>
  );
}

// ── Composer ───────────────────────────────────────────────────────────────

function Composer({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);

  // Grow the textarea up to ~5 rows, then scroll internally. Keep overflow
  // hidden below the cap — otherwise a phantom scrollbar gutter renders at
  // one line.
  const autosize = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 132)}px`;
    el.style.overflowY = el.scrollHeight > 132 ? 'auto' : 'hidden';
  };

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText('');
    requestAnimationFrame(autosize);
  };

  return (
    <div className="flex-shrink-0 border-t border-hairline bg-paper px-6 py-4">
      {/* AskPanel-style chrome: one bordered container, borderless textarea
          inside, compact send button embedded — no double borders or rings. */}
      <div className="mx-auto flex max-w-[760px] items-end gap-2 rounded-r10 border border-hairline-2 bg-vellum py-[6px] pl-[14px] pr-[6px] transition-colors duration-[120ms] focus-within:border-ink-3">
        <textarea
          ref={ref}
          value={text}
          rows={1}
          disabled={disabled}
          placeholder={
            disabled ? 'poltergeist is responding…' : 'message poltergeist…'
          }
          onChange={(e) => {
            setText(e.target.value);
            autosize();
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          className="flex-1 resize-none overflow-y-hidden border-none bg-transparent py-[7px] text-14 leading-[1.5] text-ink-0 placeholder:text-ink-3 focus:outline-none disabled:opacity-60"
        />
        <button
          type="button"
          aria-label="send"
          disabled={disabled || text.trim().length === 0}
          onClick={submit}
          className="mb-[1px] flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-r6 bg-neon transition-all duration-[120ms] hover:bg-neon-dark disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Lucide name="arrow-up" size={15} color="#0E0F12" />
        </button>
      </div>
    </div>
  );
}
