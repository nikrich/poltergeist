import { useEffect, useState } from 'react';
import type { Editor } from '@tiptap/core';
import { Lucide } from './Lucide';

interface Props {
  editor: Editor | null;
  onPhoto: () => void;
}

export function EditorToolbar({ editor, onPhoto }: Props) {
  // Re-render on selection/content changes so active states stay accurate.
  const [, force] = useState(0);
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
  const C = editor.chain().focus();

  const items: Array<{ name: string; icon: string; on: () => void; active?: boolean }> = [
    { name: 'bold', icon: 'bold', on: () => C.toggleBold().run(), active: editor.isActive('bold') },
    { name: 'italic', icon: 'italic', on: () => C.toggleItalic().run(), active: editor.isActive('italic') },
    { name: 'heading 1', icon: 'heading-1', on: () => C.toggleHeading({ level: 1 }).run(), active: editor.isActive('heading', { level: 1 }) },
    { name: 'heading 2', icon: 'heading-2', on: () => C.toggleHeading({ level: 2 }).run(), active: editor.isActive('heading', { level: 2 }) },
    { name: 'bullet list', icon: 'list', on: () => C.toggleBulletList().run(), active: editor.isActive('bulletList') },
    { name: 'task list', icon: 'list-checks', on: () => C.toggleTaskList().run(), active: editor.isActive('taskList') },
    { name: 'quote', icon: 'quote', on: () => C.toggleBlockquote().run(), active: editor.isActive('blockquote') },
    { name: 'code', icon: 'code', on: () => C.toggleCode().run(), active: editor.isActive('code') },
  ];

  return (
    <div className="flex flex-shrink-0 items-center gap-1 border-b border-hairline px-2 py-1">
      {items.map((it) => (
        <button
          key={it.name}
          type="button"
          aria-label={it.name}
          onMouseDown={(e) => e.preventDefault()}
          onClick={it.on}
          className={`flex h-6 w-6 items-center justify-center rounded-sm hover:bg-fog ${
            it.active ? 'bg-fog text-ink-0' : 'text-ink-2'
          }`}
        >
          <Lucide name={it.icon} size={13} />
        </button>
      ))}
      <button
        type="button"
        aria-label="photo"
        onMouseDown={(e) => e.preventDefault()}
        onClick={onPhoto}
        className="ml-auto flex items-center gap-1 rounded-sm border border-neon/30 px-2 py-[3px] text-11 text-neon hover:bg-neon-mist"
      >
        <Lucide name="camera" size={12} /> photo
      </button>
    </div>
  );
}
