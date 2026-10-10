import { describe, it, expect } from 'vitest';
import { fireEvent } from '@testing-library/react';
import { splitAltWidth } from '../lib/editor/image';
import { snapWidth } from '../lib/editor/image-view';
import { findNodePos, makeEditor, markdownOf } from './helpers/editor';

describe('splitAltWidth', () => {
  it('splits a trailing |digits into width', () => {
    expect(splitAltWidth('whiteboard|480')).toEqual({ alt: 'whiteboard', width: 480 });
    expect(splitAltWidth('|320')).toEqual({ alt: '', width: 320 });
  });
  it('leaves non-width pipes and zero alone', () => {
    expect(splitAltWidth('a|b')).toEqual({ alt: 'a|b', width: null });
    expect(splitAltWidth('a|0')).toEqual({ alt: 'a|0', width: null });
    expect(splitAltWidth('x|480x320')).toEqual({ alt: 'x|480x320', width: null });
    expect(splitAltWidth(null)).toEqual({ alt: null, width: null });
  });
});

describe('snapWidth', () => {
  it('snaps to 25/50/75% of the container and returns null at 100%', () => {
    expect(snapWidth(390, 800)).toBe(400);
    expect(snapWidth(100, 800)).toBe(200);
    expect(snapWidth(620, 800)).toBe(600);
    expect(snapWidth(760, 800)).toBeNull();
  });
  it('without a measurable container, keeps the raw width above the minimum', () => {
    expect(snapWidth(30, 0)).toBe(48);
    expect(snapWidth(333.6, 0)).toBe(334);
  });
});

describe('image width attribute', () => {
  it('parses width and keeps clean alt', () => {
    const editor = makeEditor('![whiteboard|480](90-meta/assets/a.jpg)');
    expect(editor.getJSON().content?.[0]).toMatchObject({
      type: 'image',
      attrs: { alt: 'whiteboard', width: 480, src: '90-meta/assets/a.jpg' },
    });
  });

  it('setImageWidth writes and clears the alt-pipe', () => {
    const editor = makeEditor('![a](x.jpg)');
    editor.commands.setNodeSelection(findNodePos(editor, (n) => n.type.name === 'image'));
    editor.commands.setImageWidth(240);
    expect(markdownOf(editor)).toBe('![a|240](x.jpg)');
    editor.commands.setImageWidth(null);
    expect(markdownOf(editor)).toBe('![a](x.jpg)');
  });

  it('renders the stored width on the img', () => {
    const editor = makeEditor('![a|240](x.jpg)');
    const img = editor.view.dom.querySelector<HTMLImageElement>('img.gb-jot-img')!;
    expect(img.style.width).toBe('240px');
    expect(img.getAttribute('src')).toBe('gbasset://asset/x.jpg');
  });
});

describe('resize handle', () => {
  function stubSizes(editor: ReturnType<typeof makeEditor>, imgWidth: number, container: number) {
    const img = editor.view.dom.querySelector<HTMLImageElement>('img.gb-jot-img')!;
    img.getBoundingClientRect = () => ({ width: imgWidth } as DOMRect);
    Object.defineProperty(editor.view.dom, 'clientWidth', { configurable: true, value: container });
  }

  it('dragging the handle snaps and stores the width', () => {
    const editor = makeEditor('![a](x.jpg)');
    stubSizes(editor, 800, 800);
    const handle = editor.view.dom.querySelector('[aria-label="resize image"]')!;
    fireEvent.mouseDown(handle, { clientX: 800 });
    fireEvent.mouseMove(window, { clientX: 500 });
    fireEvent.mouseUp(window, { clientX: 410 });
    expect(markdownOf(editor)).toBe('![a|400](x.jpg)');
  });

  it('dragging back to full width removes the width', () => {
    const editor = makeEditor('![a|200](x.jpg)');
    stubSizes(editor, 200, 800);
    const handle = editor.view.dom.querySelector('[aria-label="resize image"]')!;
    fireEvent.mouseDown(handle, { clientX: 200 });
    fireEvent.mouseUp(window, { clientX: 790 });
    expect(markdownOf(editor)).toBe('![a](x.jpg)');
  });

  it('hides the handle in a read-only editor', () => {
    const editor = makeEditor('![a](x.jpg)', false);
    expect(editor.view.dom.querySelector<HTMLElement>('[aria-label="resize image"]')!.hidden).toBe(true);
  });
});
