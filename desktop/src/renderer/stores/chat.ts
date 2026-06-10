import { create } from 'zustand';
import type { ChatStreamEvent, ChatToolUse } from '../../shared/api-types';

export interface StreamState {
  /** The user message this turn answers — rendered optimistically until the
   *  refetched conversation includes it. */
  userText: string;
  text: string;
  tools: ChatToolUse[];
}

export interface TurnError {
  message: string;
  /** The user message that triggered the failed turn — kept so the inline
   *  error banner can offer a retry that re-sends the original text. */
  userText: string;
}

interface ChatState {
  activeId: string | null;
  /** In-flight turn per conversation. Presence = streaming. */
  streams: Record<string, StreamState>;
  /** Last turn error per conversation, shown inline in the thread. */
  errors: Record<string, TurnError>;
  setActive: (id: string | null) => void;
  beginStream: (id: string, userText: string) => void;
  applyEvent: (id: string, event: ChatStreamEvent) => void;
  /** Finalizer for streams that end without a terminal event (user stop,
   *  relay teardown). No-op when the stream is already gone. */
  endStream: (id: string) => void;
}

export const useChat = create<ChatState>((set) => ({
  activeId: null,
  streams: {},
  errors: {},
  setActive: (id) => set({ activeId: id }),
  beginStream: (id, userText) =>
    set((s) => {
      const errors = { ...s.errors };
      delete errors[id];
      return {
        streams: { ...s.streams, [id]: { userText, text: '', tools: [] } },
        errors,
      };
    }),
  applyEvent: (id, event) =>
    set((s) => {
      const cur = s.streams[id];
      if (!cur) return {};
      switch (event.type) {
        case 'delta':
          return {
            streams: { ...s.streams, [id]: { ...cur, text: cur.text + event.text } },
          };
        case 'tool':
          return {
            streams: {
              ...s.streams,
              [id]: {
                ...cur,
                tools: [...cur.tools, { name: event.name, summary: event.summary }],
              },
            },
          };
        case 'done': {
          const streams = { ...s.streams };
          delete streams[id];
          return { streams };
        }
        case 'error': {
          const streams = { ...s.streams };
          delete streams[id];
          return {
            streams,
            errors: {
              ...s.errors,
              [id]: { message: event.message, userText: cur.userText },
            },
          };
        }
        default:
          return {};
      }
    }),
  endStream: (id) =>
    set((s) => {
      if (!s.streams[id]) return {};
      const streams = { ...s.streams };
      delete streams[id];
      return { streams };
    }),
}));
