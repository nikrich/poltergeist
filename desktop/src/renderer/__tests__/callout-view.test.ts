import { describe, it, expect } from 'vitest';
import { fireEvent } from '@testing-library/react';
import { makeEditor, markdownOf } from './helpers/editor';
import { nextFoldable } from '../lib/editor/callout-view';

function q<T extends Element>(root: Element, sel: string): T {
  const el = root.querySelector(sel);
  if (!el) throw new Error(`missing ${sel}`);
  return el as T;
}

describe('callout node view', () => {
  it('renders header + body with kind and title', () => {
    const editor = makeEditor('> [!warning] Careful\n> body');
    const dom = q<HTMLElement>(editor.view.dom, '.gb-callout');
    expect(dom.dataset.kind).toBe('warning');
    expect(q<HTMLInputElement>(dom, '[aria-label="callout title"]').value).toBe('Careful');
    expect(q<HTMLSelectElement>(dom, '[aria-label="callout type"]').value).toBe('warning');
    expect(q<HTMLElement>(dom, '.gb-callout-body').textContent).toBe('body');
  });

  it('hides the chevron for non-foldable callouts', () => {
    const editor = makeEditor('> [!info] T\n> body');
    expect(q<HTMLButtonElement>(editor.view.dom, '[aria-label="toggle callout"]').hidden).toBe(true);
  });

  it('chevron toggles foldable and writes the marker to markdown', () => {
    const editor = makeEditor('> [!note]+ Details\n> body');
    const chevron = q<HTMLButtonElement>(editor.view.dom, '[aria-label="toggle callout"]');
    fireEvent.click(chevron);
    expect(markdownOf(editor)).toBe('> [!note]- Details\n> body');
    expect(q<HTMLElement>(editor.view.dom, '.gb-callout').dataset.collapsed).toBe('true');
    fireEvent.click(q(editor.view.dom, '[aria-label="toggle callout"]'));
    expect(markdownOf(editor)).toBe('> [!note]+ Details\n> body');
  });

  it('title input commits a sanitised title; blank removes it', () => {
    const editor = makeEditor('> [!info] Old\n> body');
    const input = q<HTMLInputElement>(editor.view.dom, '[aria-label="callout title"]');
    fireEvent.change(input, { target: { value: '  New   title ' } });
    expect(markdownOf(editor)).toBe('> [!info] New title\n> body');
    fireEvent.change(q(editor.view.dom, '[aria-label="callout title"]'), { target: { value: '  ' } });
    expect(markdownOf(editor)).toBe('> [!info]\n> body');
  });

  it('kind select changes the callout type', () => {
    const editor = makeEditor('> [!info] T\n> body');
    fireEvent.change(q(editor.view.dom, '[aria-label="callout type"]'), { target: { value: 'error' } });
    expect(markdownOf(editor)).toBe('> [!error] T\n> body');
  });

  it('read-only: chevron folds visually but never changes the document', () => {
    const editor = makeEditor('> [!note]+ Details\n> body', false);
    fireEvent.click(q(editor.view.dom, '[aria-label="toggle callout"]'));
    expect(markdownOf(editor)).toBe('> [!note]+ Details\n> body');
    expect(q<HTMLElement>(editor.view.dom, '.gb-callout').dataset.collapsed).toBe('true');
    expect(q<HTMLInputElement>(editor.view.dom, '[aria-label="callout title"]').readOnly).toBe(true);
  });

  it('nextFoldable flips open/closed', () => {
    expect(nextFoldable('open')).toBe('closed');
    expect(nextFoldable('closed')).toBe('open');
  });
});
