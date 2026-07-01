import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Editor } from '@tiptap/core';
import { buildEditorExtensions } from '../lib/editor/extensions';
import { getMarkdown } from '../lib/editor/markdown';
import { insertImageFile } from '../lib/editor/insert-image';

beforeEach(() => {
  window.gb = {
    ...window.gb,
    assets: {
      write: vi.fn(async () => ({ ok: true as const, path: '90-meta/assets/jots/2026/06/j-9.png' })),
      toUrl: (p: string) => 'gbasset://asset/' + p,
    },
  };
});

describe('insertImageFile', () => {
  it('writes the asset and inserts a markdown image at the cursor', async () => {
    const editor = new Editor({ extensions: buildEditorExtensions(), content: 'hello' });
    const file = new File([new Uint8Array([1, 2, 3])], 'shot.png', { type: 'image/png' });
    const p = await insertImageFile(editor, 'jotid123', file);
    expect(p).toBe('90-meta/assets/jots/2026/06/j-9.png');
    expect(window.gb.assets.write).toHaveBeenCalledWith(
      expect.objectContaining({ jotId: 'jotid123', ext: 'png' }),
    );
    expect(getMarkdown(editor)).toContain('![](90-meta/assets/jots/2026/06/j-9.png)');
    editor.destroy();
  });

  it('throws and inserts no image node when the asset write fails', async () => {
    window.gb = {
      ...window.gb,
      assets: {
        write: vi.fn(async (): Promise<{ ok: false; error: string }> => ({
          ok: false,
          error: 'disk full',
        })),
        toUrl: (p: string) => 'gbasset://asset/' + p,
      },
    };
    const editor = new Editor({ extensions: buildEditorExtensions(), content: 'hello' });
    const file = new File([new Uint8Array([1, 2, 3])], 'photo.jpg', { type: 'image/jpeg' });
    await expect(insertImageFile(editor, 'jotid456', file)).rejects.toThrow('disk full');
    expect(getMarkdown(editor)).not.toContain('![');
    expect(getMarkdown(editor)).not.toContain('90-meta/assets');
    editor.destroy();
  });
});
