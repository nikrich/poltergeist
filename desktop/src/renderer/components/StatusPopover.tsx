import { useState } from 'react';
import type { Editor } from '@tiptap/core';
import {
  STATUS_COLORS,
  sanitizeStatusLabel,
  type StatusAttrs,
  type StatusColor,
} from '../lib/editor/status';

interface Props {
  editor: Editor;
  pos: number;
  onClose: () => void;
}

function anchor(editor: Editor, pos: number): { top: number; left: number } {
  try {
    const c = editor.view.coordsAtPos(pos);
    return { top: c.bottom + 4, left: c.left };
  } catch {
    return { top: 0, left: 0 }; // jsdom / detached view
  }
}

export function StatusPopover({ editor, pos, onClose }: Props) {
  const node = editor.state.doc.nodeAt(pos);
  const initial = node?.type.name === 'status' ? (node.attrs as StatusAttrs) : null;
  const [label, setLabel] = useState(initial?.label ?? '');
  const [color, setColor] = useState<StatusColor>(initial?.color ?? 'grey');

  if (!initial) return null;
  const { top, left } = anchor(editor, pos);

  function save(): void {
    const clean = sanitizeStatusLabel(label.replace(/`/g, ''));
    if (!clean) return;
    editor.chain().focus().updateStatusAt(pos, { label: clean, color }).run();
    onClose();
  }

  return (
    <div
      role="dialog"
      aria-label="edit status"
      style={{ position: 'fixed', top, left, zIndex: 9999 }}
      className="flex w-56 flex-col gap-2 rounded border border-hairline bg-vellum p-2 shadow-md"
    >
      <input
        aria-label="status label"
        autoFocus
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            save();
          } else if (e.key === 'Escape') {
            e.preventDefault();
            onClose();
          }
        }}
        className="rounded-sm border border-hairline bg-paper px-2 py-1 font-mono text-11 text-ink-0 outline-none"
      />
      <div className="flex items-center gap-1">
        {STATUS_COLORS.map((c) => (
          <button
            key={c}
            type="button"
            aria-label={`colour ${c}`}
            aria-pressed={c === color}
            onClick={() => setColor(c)}
            className={`gb-status gb-status-${c} ${c === color ? 'bg-fog' : ''}`}
          >
            {c.slice(0, 2)}
          </button>
        ))}
        <button
          type="button"
          onClick={save}
          className="ml-auto rounded-sm px-2 py-[2px] font-mono text-10 text-neon hover:bg-neon-mist"
        >
          save
        </button>
      </div>
    </div>
  );
}
