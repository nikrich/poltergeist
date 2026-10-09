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
      current = props;
      highlighted = 0;
      dismissed = false;
      paint();
    },
    onUpdate(props) {
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
      const session = { show: false, indexing: false };
      return [
        Suggestion<SuggestItem, SuggestItem>({
          editor: this.editor,
          pluginKey: new PluginKey(cfg.name),
          char: cfg.char,
          allowSpaces: cfg.allowSpaces,
          allowedPrefixes: cfg.allowedPrefixes,
          startOfLine: false,
          items: async ({ query }) => {
            if (query.length < cfg.minQueryLength || cfg.rejectQuery?.test(query)) {
              session.show = false;
              session.indexing = false;
              return [];
            }
            const result = await fetcher(cfg.kind, query);
            session.show = true;
            session.indexing = result.indexing;
            return result.items;
          },
          command: ({ editor, range, props }) => {
            const text = `${linkTextFor(props, { inTable: isInTable(editor) })} `;
            // A text node, not a string: tiptap-markdown would parse a string as markdown.
            editor.chain().focus().deleteRange(range).insertContent({ type: 'text', text }).run();
          },
          render: () =>
            renderSuggestPopup(() =>
              !session.show ? null : session.indexing ? 'indexing vault…' : 'no suggestions',
            ),
        }),
      ];
    },
  });
}
