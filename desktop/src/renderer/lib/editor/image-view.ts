import type { Editor } from '@tiptap/core';
import type { Node as PMNode } from 'prosemirror-model';
import type { NodeView } from '@tiptap/pm/view';
import { toDisplaySrc } from './image';

export const SNAP_FRACTIONS = [0.25, 0.5, 0.75, 1] as const;
export const MIN_IMAGE_WIDTH = 48;

/** Snap to 25/50/75/100% of the editor width; 100% → null (no width stored). */
export function snapWidth(px: number, containerPx: number): number | null {
  if (containerPx <= 0) return Math.max(MIN_IMAGE_WIDTH, Math.round(px));
  let best: number = SNAP_FRACTIONS[0] * containerPx;
  for (const f of SNAP_FRACTIONS) {
    const stop = f * containerPx;
    if (Math.abs(stop - px) < Math.abs(best - px)) best = stop;
  }
  return best >= containerPx ? null : Math.round(best);
}

export function createImageView(node: PMNode, editor: Editor, getPos: () => number | undefined): NodeView {
  let current = node;
  const dom = document.createElement('div');
  dom.className = 'gb-img-wrap';
  const img = document.createElement('img');
  img.className = 'gb-jot-img';
  img.draggable = false;
  const handle = document.createElement('span');
  handle.className = 'gb-img-handle';
  handle.setAttribute('role', 'separator');
  handle.setAttribute('aria-label', 'resize image');
  dom.append(img, handle);

  const sync = (): void => {
    const a = current.attrs as { src: string | null; alt: string | null; title: string | null; width: number | null };
    img.src = toDisplaySrc(a.src ?? '');
    img.alt = a.alt ?? '';
    if (a.title) img.title = a.title;
    else img.removeAttribute('title');
    img.style.width = a.width ? `${a.width}px` : '';
    handle.hidden = !editor.isEditable;
  };

  handle.addEventListener('mousedown', (down) => {
    down.preventDefault();
    down.stopPropagation();
    const startX = down.clientX;
    const startW = img.getBoundingClientRect().width;
    const onMove = (ev: MouseEvent): void => {
      img.style.width = `${Math.max(MIN_IMAGE_WIDTH, startW + ev.clientX - startX)}px`;
    };
    const onUp = (ev: MouseEvent): void => {
      // Always detach both listeners first, whatever happens below.
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      const width = snapWidth(startW + ev.clientX - startX, editor.view.dom.clientWidth);
      const pos = getPos();
      if (typeof pos !== 'number' || width === current.attrs.width) {
        sync(); // restore the pre-drag style
        return;
      }
      editor.view.dispatch(editor.state.tr.setNodeMarkup(pos, undefined, { ...current.attrs, width }));
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  });

  sync();

  return {
    dom,
    update(next) {
      if (next.type !== current.type) return false;
      current = next;
      sync();
      return true;
    },
    selectNode() {
      dom.classList.add('ProseMirror-selectednode');
    },
    deselectNode() {
      dom.classList.remove('ProseMirror-selectednode');
    },
    stopEvent: (event) => event.target === handle,
    ignoreMutation: () => true,
  };
}
