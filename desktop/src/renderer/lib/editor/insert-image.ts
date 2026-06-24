import type { Editor } from '@tiptap/core';

function extFor(file: File): string {
  const fromName = file.name.includes('.') ? file.name.split('.').pop()! : '';
  if (fromName) return fromName.toLowerCase();
  const fromType = file.type.split('/')[1] ?? 'png';
  return fromType.toLowerCase();
}

/** Write a File into the vault and insert an inline image node at the cursor. */
export async function insertImageFile(editor: Editor, jotId: string, file: File): Promise<void> {
  const bytes = await file.arrayBuffer();
  const res = await window.gb.assets.write({ jotId, ext: extFor(file), bytes });
  if (!res.ok) throw new Error(res.error);
  editor.chain().focus().insertContent({ type: 'image', attrs: { src: res.path } }).run();
}
