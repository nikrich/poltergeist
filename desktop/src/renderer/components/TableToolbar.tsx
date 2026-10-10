import { useEffect, useState } from 'react';
import type { ChainedCommands, Editor } from '@tiptap/core';
import type { CellAlign } from '../lib/editor/table';

interface Props {
  editor: Editor;
}

interface TableAction {
  label: string;
  text: string;
  run: (chain: ChainedCommands) => ChainedCommands;
  can: (editor: Editor) => boolean;
  align?: CellAlign;
}

export const TABLE_ACTIONS: TableAction[] = [
  { label: 'add row above', text: '+row ↑', run: (c) => c.addRowBefore(), can: (e) => e.can().addRowBefore() },
  { label: 'add row below', text: '+row ↓', run: (c) => c.addRowAfter(), can: (e) => e.can().addRowAfter() },
  { label: 'delete row', text: '−row', run: (c) => c.deleteRow(), can: (e) => e.can().deleteRow() },
  { label: 'add column left', text: '+col ←', run: (c) => c.addColumnBefore(), can: (e) => e.can().addColumnBefore() },
  { label: 'add column right', text: '+col →', run: (c) => c.addColumnAfter(), can: (e) => e.can().addColumnAfter() },
  { label: 'delete column', text: '−col', run: (c) => c.deleteColumn(), can: (e) => e.can().deleteColumn() },
  { label: 'toggle header row', text: 'header', run: (c) => c.toggleHeaderRow(), can: (e) => e.can().toggleHeaderRow() },
  { label: 'align left', text: 'left', align: 'left', run: (c) => c.setColumnAlign('left'), can: (e) => e.can().setColumnAlign('left') },
  { label: 'align centre', text: 'centre', align: 'center', run: (c) => c.setColumnAlign('center'), can: (e) => e.can().setColumnAlign('center') },
  { label: 'align right', text: 'right', align: 'right', run: (c) => c.setColumnAlign('right'), can: (e) => e.can().setColumnAlign('right') },
  { label: 'delete table', text: 'delete table', run: (c) => c.deleteTable(), can: (e) => e.can().deleteTable() },
];

export function TableToolbar({ editor }: Props) {
  // Re-render on selection/content changes (same pattern as EditorToolbar).
  const [, force] = useState(0);
  useEffect(() => {
    const update = () => force((n) => n + 1);
    editor.on('selectionUpdate', update);
    editor.on('transaction', update);
    return () => {
      editor.off('selectionUpdate', update);
      editor.off('transaction', update);
    };
  }, [editor]);

  if (editor.isDestroyed || !editor.isEditable || !editor.isActive('table')) return null;

  const current = ((editor.getAttributes('tableCell').align as CellAlign | null | undefined) ??
    (editor.getAttributes('tableHeader').align as CellAlign | null | undefined) ??
    null) as CellAlign | null;

  return (
    <div
      role="toolbar"
      aria-label="table controls"
      className="sticky top-0 z-10 flex flex-wrap items-center gap-1 border-b border-hairline bg-vellum px-2 py-1 font-mono text-10 text-ink-2"
    >
      {TABLE_ACTIONS.map((a) => (
        <button
          key={a.label}
          type="button"
          aria-label={a.label}
          aria-pressed={a.align ? a.align === current : undefined}
          disabled={!a.can(editor)}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => a.run(editor.chain().focus()).run()}
          className={`rounded-sm px-[6px] py-[2px] hover:bg-fog hover:text-ink-0 disabled:opacity-40 ${
            a.align && a.align === current ? 'bg-fog text-ink-0' : ''
          } ${a.label === 'delete table' ? 'ml-auto text-oxblood' : ''}`}
        >
          {a.text}
        </button>
      ))}
    </div>
  );
}
