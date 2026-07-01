import { Extension } from '@tiptap/core';
import type { Editor, Range } from '@tiptap/core';
import { Suggestion } from '@tiptap/suggestion';
import type { SuggestionProps, SuggestionKeyDownProps } from '@tiptap/suggestion';
import * as ReactDOM from 'react-dom/client';
import { createElement } from 'react';
import { SlashMenu } from '../../components/SlashMenu';

export interface SlashItem {
  key: string;
  title: string;
  run: (editor: Editor, range: Range) => void;
}

export const SLASH_ITEMS: SlashItem[] = [
  { key: 'h1', title: 'Heading 1', run: (e, r) => e.chain().focus().deleteRange(r).setHeading({ level: 1 }).run() },
  { key: 'h2', title: 'Heading 2', run: (e, r) => e.chain().focus().deleteRange(r).setHeading({ level: 2 }).run() },
  { key: 'h3', title: 'Heading 3', run: (e, r) => e.chain().focus().deleteRange(r).setHeading({ level: 3 }).run() },
  { key: 'bullet', title: 'Bullet list', run: (e, r) => e.chain().focus().deleteRange(r).toggleBulletList().run() },
  { key: 'task', title: 'Task list', run: (e, r) => e.chain().focus().deleteRange(r).toggleTaskList().run() },
  { key: 'quote', title: 'Quote', run: (e, r) => e.chain().focus().deleteRange(r).toggleBlockquote().run() },
  { key: 'code', title: 'Code block', run: (e, r) => e.chain().focus().deleteRange(r).toggleCodeBlock().run() },
  { key: 'divider', title: 'Divider', run: (e, r) => e.chain().focus().deleteRange(r).setHorizontalRule().run() },
  { key: 'table', title: 'Table', run: (e, r) => e.chain().focus().deleteRange(r).insertTable({ rows: 2, cols: 2, withHeaderRow: true }).run() },
  {
    key: 'photo',
    title: 'Photo (webcam)',
    run: (e, r) => {
      e.chain().focus().deleteRange(r).run();
      // EditorEvents is a closed interface; gb:slash:photo is a custom event.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (e as any).emit('gb:slash:photo');
    },
  },
];

export function filterSlashItems(query: string): SlashItem[] {
  const q = query.toLowerCase();
  return SLASH_ITEMS.filter((i) => i.title.toLowerCase().includes(q));
}

/** Factory returned to Suggestion's `render` hook. */
export function renderSlashPopup(): {
  onStart: (props: SuggestionProps<SlashItem>) => void;
  onUpdate: (props: SuggestionProps<SlashItem>) => void;
  onKeyDown: (props: SuggestionKeyDownProps) => boolean;
  onExit: () => void;
} {
  let container: HTMLDivElement | null = null;
  let root: ReactDOM.Root | null = null;
  let highlightedIndex = 0;
  let currentProps: SuggestionProps<SlashItem> | null = null;

  function mount(props: SuggestionProps<SlashItem>): void {
    currentProps = props;
    highlightedIndex = 0;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = ReactDOM.createRoot(container);
    render(props);
  }

  function render(props: SuggestionProps<SlashItem>): void {
    const rect = props.clientRect?.() ?? null;
    const top = rect ? rect.bottom + window.scrollY + 4 : 0;
    const left = rect ? rect.left + window.scrollX : 0;
    root?.render(
      createElement(SlashMenu, {
        items: props.items,
        highlightedIndex,
        top,
        left,
        onSelect: (item: SlashItem) => props.command(item),
      }),
    );
  }

  return {
    onStart(props) {
      mount(props);
    },
    onUpdate(props) {
      currentProps = props;
      highlightedIndex = 0;
      render(props);
    },
    onKeyDown({ event }) {
      if (!currentProps) return false;
      const items = currentProps.items;
      if (event.key === 'ArrowDown') {
        highlightedIndex = (highlightedIndex + 1) % Math.max(items.length, 1);
        render(currentProps);
        return true;
      }
      if (event.key === 'ArrowUp') {
        highlightedIndex = (highlightedIndex - 1 + Math.max(items.length, 1)) % Math.max(items.length, 1);
        render(currentProps);
        return true;
      }
      if (event.key === 'Enter') {
        const item = items[highlightedIndex];
        if (item) currentProps.command(item);
        return true;
      }
      if (event.key === 'Escape') {
        root?.unmount();
        container?.remove();
        root = null;
        container = null;
        currentProps = null;
        return true;
      }
      return false;
    },
    onExit() {
      root?.unmount();
      container?.remove();
      root = null;
      container = null;
      currentProps = null;
    },
  };
}

export const SlashExtension = Extension.create({
  name: 'slashCommands',
  addProseMirrorPlugins() {
    return [
      Suggestion<SlashItem>({
        editor: this.editor,
        char: '/',
        startOfLine: false,
        command: ({ editor, range, props }) => props.run(editor, range),
        items: ({ query }) => filterSlashItems(query),
        render: renderSlashPopup,
      }),
    ];
  },
});
