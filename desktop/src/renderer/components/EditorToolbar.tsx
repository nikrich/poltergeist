import { useEffect, useRef, useState } from 'react';
import type { Editor } from '@tiptap/core';
import { isInTable } from '@tiptap/pm/tables';
import { insertEntries, runInsert, type InsertEntry } from '../lib/editor/insert-menu';
import {
  LIST_ACTIONS,
  MARK_ACTIONS,
  TEXT_STYLES,
  currentTextStyle,
  shortcutText,
  withShortcut,
  type TextStyle,
  type ToolbarAction,
} from '../lib/editor/toolbar-actions';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { LinkEditor } from './editor-toolbar/LinkEditor';
import { FOCUS_RING, ToolbarMenu, type ToolbarMenuItem } from './editor-toolbar/ToolbarMenu';
import { Lucide } from './Lucide';
import { shortcutLabel } from '../lib/editor-shortcuts';

export interface EditorToolbarProps {
  editor: Editor | null;
  /** Inserts a picked image file. Absent → no Image row (read-only). */
  onImageFile?: (file: File) => void;
  /** A5 inline AI. Absent → no Ask AI row. */
  onAssist?: () => void;
}

/** 1px rule between button groups (Confluence's toolbar separators). */
const Rule = () => <span aria-hidden className="mx-[6px] h-5 w-px flex-shrink-0 bg-hairline-2" />;

const ICON_BUTTON = `flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-sm transition-colors duration-100 hover:bg-fog hover:text-ink-0 disabled:cursor-default disabled:text-ink-3 disabled:hover:bg-transparent ${FOCUS_RING}`;

const iconButtonClass = (on: boolean) => `${ICON_BUTTON} ${on ? 'bg-hairline-2 text-ink-0' : 'text-ink-2'}`;

/** Each text-style row previews its style, stepping down like the page's headings. */
const STYLE_PREVIEW: Record<TextStyle['id'], string> = {
  paragraph: 'text-13',
  h1: 'font-display text-18 font-semibold tracking-tight-xx',
  h2: 'font-display text-16 font-semibold tracking-tight-xx',
  h3: 'font-display text-14 font-semibold',
};

/** Visual sections of the Insert menu: panels, page elements, media, blocks, AI. */
function insertGroup(en: InsertEntry): string {
  if (['info', 'note', 'success', 'warning', 'error', 'tip'].includes(en.key)) return 'panels';
  if (['expand', 'status', 'toc', 'diagram'].includes(en.key)) return 'elements';
  if (en.key === 'image' || en.key === 'photo') return 'media';
  if (en.kind === 'assist') return 'assist';
  return 'blocks';
}

function ActionButton({ editor, action }: { editor: Editor; action: ToolbarAction }) {
  const on = action.isActive(editor);
  return (
    <button
      type="button"
      aria-label={action.id}
      title={withShortcut(action.label, action.shortcut)}
      aria-pressed={on}
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => action.run(editor)}
      className={iconButtonClass(on)}
    >
      <Lucide name={action.icon} size={14} />
    </button>
  );
}

function PageWidthToggle() {
  const width = useSettings((s) => s.pageWidth);
  const set = useSettings((s) => s.set);
  const full = width === 'full';
  return (
    <button
      type="button"
      aria-label="full width"
      aria-pressed={full}
      title={full ? 'Fixed width' : 'Full width'}
      onMouseDown={(e) => e.preventDefault()}
      onClick={() =>
        void set('pageWidth', full ? 'fixed' : 'full').then((r) => {
          if (!r.ok) toast.error(r.error);
        })
      }
      className={iconButtonClass(full)}
    >
      <Lucide name={full ? 'fold-horizontal' : 'unfold-horizontal'} size={14} />
    </button>
  );
}

/** A7: the page's one fixed formatting toolbar (Confluence layout). */
export function EditorToolbar({ editor, onImageFile, onAssist }: EditorToolbarProps) {
  // Re-render on selection/content changes so active states stay accurate.
  const [, force] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!editor) return;
    const update = () => force((n) => n + 1);
    editor.on('selectionUpdate', update);
    editor.on('transaction', update);
    return () => {
      editor.off('selectionUpdate', update);
      editor.off('transaction', update);
    };
  }, [editor]);

  if (!editor) return null;

  const inTable = isInTable(editor.state);
  // A code block has no text style; "Normal text" there would be misleading.
  const inCode = editor.isActive('codeBlock');

  const styleItems: ToolbarMenuItem[] = TEXT_STYLES.map((s) => ({
    key: s.id,
    label: s.label,
    hint: shortcutText(s.shortcut),
    checked: s.isActive(editor),
    labelClassName: STYLE_PREVIEW[s.id],
    onSelect: () => s.run(editor),
  }));

  const insertItems: ToolbarMenuItem[] = insertEntries({
    canPickImage: onImageFile !== undefined,
    canAssist: onAssist !== undefined,
    inTable,
  }).map((en) => ({
    key: en.key,
    label: en.label,
    icon: en.icon,
    group: insertGroup(en),
    // A5 binds ⌘J to the same inline AI; this row is its one toolbar entry.
    hint: en.kind === 'assist' ? shortcutLabel('inlineAi') : undefined,
    onSelect: () => {
      if (en.kind === 'image') fileRef.current?.click();
      else if (en.kind === 'assist') onAssist?.();
      else runInsert(editor, en.key);
    },
  }));

  return (
    <div
      role="toolbar"
      aria-label="formatting"
      className="flex h-10 flex-shrink-0 items-center gap-[2px] overflow-x-auto overflow-y-hidden border-b border-hairline bg-paper px-3 [scrollbar-width:none]"
    >
      <ToolbarMenu
        label="text style"
        title={inCode ? 'Text style (not in a code block)' : 'Text style'}
        radio
        disabled={inCode}
        items={styleItems}
        trigger={
          <>
            <span className="w-[92px] truncate text-left text-13">
              {inCode ? 'Code' : currentTextStyle(editor)}
            </span>
            <Lucide name="chevron-down" size={12} className="text-ink-3" />
          </>
        }
      />
      <Rule />
      {MARK_ACTIONS.map((a) => (
        <ActionButton key={a.id} editor={editor} action={a} />
      ))}
      <Rule />
      {LIST_ACTIONS.map((a) => (
        <ActionButton key={a.id} editor={editor} action={a} />
      ))}
      <Rule />
      <LinkEditor editor={editor} />
      <button
        type="button"
        aria-label="table"
        title={inTable ? 'Table (not inside a table)' : 'Table'}
        disabled={inTable}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => runInsert(editor, 'table')}
        className={iconButtonClass(false)}
      >
        <Lucide name="table" size={14} />
      </button>
      <Rule />
      <ToolbarMenu
        label="insert"
        title="Insert"
        items={insertItems}
        triggerClassName="text-ink-0"
        trigger={
          <>
            <Lucide name="plus" size={14} />
            <span className="text-13 font-medium">Insert</span>
            <Lucide name="chevron-down" size={12} className="text-ink-3" />
          </>
        }
      />
      <div className="ml-auto flex flex-shrink-0 items-center pl-3">
        <PageWidthToggle />
      </div>
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        hidden
        data-testid="image-picker"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = '';
          if (file && onImageFile) onImageFile(file);
        }}
      />
    </div>
  );
}
