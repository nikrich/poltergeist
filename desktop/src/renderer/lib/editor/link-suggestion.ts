import { Extension } from '@tiptap/core';
import { PluginKey } from '@tiptap/pm/state';
import { Suggestion } from '@tiptap/suggestion';
import type { SuggestionKeyDownProps, SuggestionProps } from '@tiptap/suggestion';
import { createElement } from 'react';
import * as ReactDOM from 'react-dom/client';
import { SuggestMenu } from '../../components/SuggestMenu';
import type { SuggestItem, SuggestKind } from '../../../shared/api-types';
import { createLatestFetcher, isInTable, linkTextFor, type SuggestResult } from './link-suggest';

export interface LinkSuggestConfig {
  /** Extension name; also the PluginKey name (must be unique per editor). */
  name: string;
  kind: SuggestKind;
  char: string;
  allowSpaces: boolean;
  allowedPrefixes: string[] | null;
  /** Below this query length no request is made and no menu shows. */
  minQueryLength: number;
  /** A query matching this is treated as finished (e.g. `]` closes a wikilink). */
  rejectQuery?: RegExp;
}

type Props = SuggestionProps<SuggestItem, SuggestItem>;

/** The subset of @tiptap/suggestion's plugin state this module reads. */
interface SuggestState {
  active: boolean;
  query: string | null;
  range: { from: number; to: number };
}

/** Popup lifecycle for one suggestion session (mirrors renderSlashPopup). */
export function renderSuggestPopup(emptyText: () => string | null): {
  onStart: (props: Props) => void;
  onUpdate: (props: Props) => void;
  onKeyDown: (props: SuggestionKeyDownProps) => boolean;
  onExit: () => void;
} {
  let container: HTMLDivElement | null = null;
  let root: ReactDOM.Root | null = null;
  let highlighted = 0;
  let current: Props | null = null;
  let dismissed = false;
  let visible = false;

  function close(): void {
    root?.unmount();
    container?.remove();
    root = null;
    container = null;
    visible = false;
  }

  function paint(): void {
    if (!current || dismissed) return;
    const empty = emptyText();
    visible = current.items.length > 0 || empty !== null;
    if (!visible) {
      close();
      return;
    }
    if (!root) {
      container = document.createElement('div');
      document.body.appendChild(container);
      root = ReactDOM.createRoot(container);
    }
    const rect = current.clientRect?.() ?? null;
    const props = current;
    root.render(
      createElement(SuggestMenu, {
        items: props.items,
        highlightedIndex: highlighted,
        top: rect ? rect.bottom + window.scrollY + 4 : 0,
        left: rect ? rect.left + window.scrollX : 0,
        emptyText: empty,
        onSelect: (item: SuggestItem) => props.command(item),
      }),
    );
  }

  return {
    onStart(props) {
      // @tiptap/suggestion awaits items() and then calls onStart/onUpdate unchecked:
      // never paint for an editor that was destroyed meanwhile (the popup would leak).
      if (props.editor.isDestroyed) return;
      current = props;
      highlighted = 0;
      dismissed = false;
      paint();
    },
    onUpdate(props) {
      if (props.editor.isDestroyed) return;
      current = props;
      highlighted = 0;
      paint();
    },
    onKeyDown({ event }) {
      if (!current || dismissed || !visible) return false;
      if (event.key === 'Escape') {
        dismissed = true;
        close();
        return true;
      }
      const n = current.items.length;
      if (n === 0) return false; // let Enter/arrows reach the editor
      if (event.key === 'ArrowDown') {
        highlighted = (highlighted + 1) % n;
        paint();
        return true;
      }
      if (event.key === 'ArrowUp') {
        highlighted = (highlighted - 1 + n) % n;
        paint();
        return true;
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        const item = current.items[highlighted];
        if (item) current.command(item);
        return true;
      }
      return false;
    },
    onExit() {
      close();
      current = null;
      dismissed = false;
    },
  };
}

export function createLinkSuggestExtension(
  cfg: LinkSuggestConfig,
  fetcher: (kind: SuggestKind, query: string) => Promise<SuggestResult> = createLatestFetcher(),
) {
  return Extension.create({
    name: cfg.name,
    addProseMirrorPlugins() {
      // Per-editor session state shared between items() and the popup.
      // `seq` lets only the newest items() call write show/indexing.
      const session = { show: false, indexing: false, seq: 0 };
      const pluginKey = new PluginKey<SuggestState>(cfg.name);
      const editor = this.editor;
      // items() is async and the plugin calls onStart/onUpdate after it resolves
      // without re-checking: props for a query the plugin no longer holds (the
      // session ended or moved on meanwhile) are stale and must not paint.
      const isCurrent = (props: Props): boolean => {
        if (editor.isDestroyed) return false;
        const state = pluginKey.getState(editor.state);
        return Boolean(
          state?.active && state.query === props.query && state.range.from === props.range.from,
        );
      };
      return [
        Suggestion<SuggestItem, SuggestItem>({
          editor,
          pluginKey,
          char: cfg.char,
          allowSpaces: cfg.allowSpaces,
          allowedPrefixes: cfg.allowedPrefixes,
          startOfLine: false,
          items: async ({ query }) => {
            const mine = ++session.seq;
            if (query.length < cfg.minQueryLength || cfg.rejectQuery?.test(query)) {
              session.show = false;
              session.indexing = false;
              return [];
            }
            const result = await fetcher(cfg.kind, query);
            if (mine !== session.seq) return []; // superseded (e.g. by a rejected `]` query)
            session.show = true;
            session.indexing = result.indexing;
            return result.items;
          },
          command: ({ editor, props }) => {
            // The popup's props (and their range) can lag the document while a newer
            // query's fetch is pending: always replace the plugin's live range.
            const live = pluginKey.getState(editor.state);
            if (!live?.active) return;
            const text = `${linkTextFor(props, { inTable: isInTable(editor) })} `;
            // A text node, not a string: tiptap-markdown would parse a string as markdown.
            editor.chain().focus().deleteRange(live.range).insertContent({ type: 'text', text }).run();
          },
          render: () => {
            const popup = renderSuggestPopup(() =>
              !session.show ? null : session.indexing ? 'indexing vault…' : 'no suggestions',
            );
            return {
              ...popup,
              onStart: (props: Props) => {
                if (isCurrent(props)) popup.onStart(props);
              },
              onUpdate: (props: Props) => {
                if (isCurrent(props)) popup.onUpdate(props);
              },
            };
          },
        }),
      ];
    },
  });
}
