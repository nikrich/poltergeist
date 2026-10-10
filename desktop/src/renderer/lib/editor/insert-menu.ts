import type { Editor } from '@tiptap/core';
import { isInTable } from '@tiptap/pm/tables';
import { SLASH_ITEMS, type SlashItem } from './slash';

/** One row of the toolbar's "+ Insert" menu. A 'slash' row runs A1's slash
 * command with the same key, so this menu and "/" can never drift. */
export interface InsertEntry {
  key: string;
  label: string;
  icon: string;
  kind: 'slash' | 'image' | 'assist';
}

type Row = Omit<InsertEntry, 'kind'>;

const BLOCKS: Row[] = [
  { key: 'info', label: 'Info panel', icon: 'info' },
  { key: 'note', label: 'Note panel', icon: 'sticky-note' },
  { key: 'success', label: 'Success panel', icon: 'circle-check' },
  { key: 'warning', label: 'Warning panel', icon: 'triangle-alert' },
  { key: 'error', label: 'Error panel', icon: 'circle-x' },
  { key: 'tip', label: 'Tip panel', icon: 'lightbulb' },
  { key: 'expand', label: 'Expand', icon: 'list-collapse' },
  { key: 'status', label: 'Status', icon: 'tag' },
  { key: 'toc', label: 'Table of contents', icon: 'list-tree' },
  { key: 'diagram', label: 'Mermaid diagram', icon: 'workflow' },
];

const AFTER_IMAGE: Row[] = [
  { key: 'photo', label: 'Photo (webcam)', icon: 'camera' },
  { key: 'table', label: 'Table', icon: 'table' },
  { key: 'divider', label: 'Divider', icon: 'minus' },
  { key: 'code', label: 'Code block', icon: 'square-code' },
  { key: 'quote', label: 'Quote', icon: 'quote' },
  // C1's slash item; the row is feature-checked against SLASH_ITEMS like every other.
  { key: 'template', label: 'Template', icon: 'layout-template' },
];

export interface InsertOptions {
  slashItems?: readonly SlashItem[];
  /** The editor can take a picked image file (not read-only). */
  canPickImage: boolean;
  /** A5 inline AI handler present. */
  canAssist: boolean;
  /** Cursor is in a table cell: drop blockOnly rows, as the slash menu does. */
  inTable?: boolean;
}

export function insertEntries({
  slashItems = SLASH_ITEMS,
  canPickImage,
  canAssist,
  inTable = false,
}: InsertOptions): InsertEntry[] {
  const have = new Set(slashItems.filter((i) => !(inTable && i.blockOnly)).map((i) => i.key));
  const slash = (rows: Row[]): InsertEntry[] =>
    rows.filter((r) => have.has(r.key)).map((r): InsertEntry => ({ ...r, kind: 'slash' }));
  // Ask AI leads: it is the editor's one inline-AI entry, and the menu is
  // height-capped, so a last row would sit below the fold.
  const out: InsertEntry[] = [];
  if (canAssist) out.push({ key: 'assist', label: 'Ask AI', icon: 'sparkles', kind: 'assist' });
  out.push(...slash(BLOCKS));
  if (canPickImage) out.push({ key: 'image', label: 'Image', icon: 'image', kind: 'image' });
  out.push(...slash(AFTER_IMAGE));
  return out;
}

/** Run A1's slash command `key` at the cursor (an empty range, so nothing
 * is deleted first). False for an unknown key, a read-only editor, or a
 * blockOnly item while the cursor is in a table cell (a GFM cell is one line). */
export function runInsert(
  editor: Editor,
  key: string,
  slashItems: readonly SlashItem[] = SLASH_ITEMS,
): boolean {
  const item = slashItems.find((i) => i.key === key);
  if (!item || !editor.isEditable) return false;
  if (item.blockOnly && isInTable(editor.state)) return false;
  const { from } = editor.state.selection;
  item.run(editor, { from, to: from });
  return true;
}
