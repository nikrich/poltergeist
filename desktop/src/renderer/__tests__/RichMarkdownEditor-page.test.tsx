import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { Editor } from '@tiptap/core';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';
import { getMarkdown } from '../lib/editor/markdown';
import { useSettings } from '../stores/settings';
import { textPos } from './helpers/editor';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

afterEach(() => useSettings.setState({ pageWidth: 'fixed' }));

describe('RichMarkdownEditor page canvas (A7)', () => {
  it('renders the page header above the document inside the canvas', () => {
    render(
      <RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" pageHeader={<div data-testid="hdr">hdr</div>} />,
    );
    const canvas = screen.getByTestId('page-canvas');
    const hdr = screen.getByTestId('hdr');
    const pm = canvas.querySelector('.ProseMirror');
    expect(canvas).toContainElement(hdr);
    expect(pm).not.toBeNull();
    expect(hdr.compareDocumentPosition(pm!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('renders a plain canvas as compact prose without the page chrome', () => {
    render(<RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" readOnly canvas="plain" />);
    expect(screen.queryByTestId('page-canvas')).not.toBeInTheDocument();
    const prose = screen.getByTestId('rich-markdown-editor').querySelector('.gb-prose');
    expect(prose).not.toBeNull();
    expect(prose).not.toHaveClass('gb-page-body');
    expect(prose).toHaveClass('px-4', 'py-3', 'text-14');
  });

  it('follows the page width setting; focus mode always uses the fixed measure', () => {
    useSettings.setState({ pageWidth: 'full' });
    const { rerender } = render(<RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" />);
    expect(screen.getByTestId('page-canvas')).toHaveAttribute('data-width', 'full');
    rerender(<RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" focus />);
    expect(screen.getByTestId('page-canvas')).toHaveAttribute('data-width', 'fixed');
  });

  it('keeps the header in source mode', () => {
    render(
      <RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" pageHeader={<div data-testid="hdr">hdr</div>} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'src' }));
    expect(screen.getByTestId('hdr')).toBeInTheDocument();
    expect(screen.getByTestId('page-canvas')).toContainElement(screen.getByTestId('hdr'));
    expect(screen.queryByRole('toolbar', { name: 'formatting' })).toBeNull();
  });

  it('hides the toolbar when read-only', () => {
    render(<RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" readOnly />);
    expect(screen.queryByRole('toolbar', { name: 'formatting' })).toBeNull();
  });

  it('hides the table controls in focus mode (FocusBar is the only chrome)', () => {
    const md = 'intro\n\n| name | value |\n| --- | --- |\n| alpha | 1 |';
    let editor: Editor | undefined;
    const { rerender } = render(
      <RichMarkdownEditor markdown={md} onSave={() => {}} jotId="t" onEditorReady={(e) => { editor = e; }} />,
    );
    act(() => {
      editor!.commands.setTextSelection(textPos(editor!, 'alpha'));
    });
    expect(screen.getByRole('toolbar', { name: 'table controls' })).toBeInTheDocument();
    rerender(
      <RichMarkdownEditor markdown={md} onSave={() => {}} jotId="t" focus onEditorReady={(e) => { editor = e; }} />,
    );
    expect(screen.queryByRole('toolbar', { name: 'table controls' })).toBeNull();
  });

  it('inserts a picked image file into the page', async () => {
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="body"
        onSave={() => {}}
        jotId="j1"
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    const file = new File([new Uint8Array([1, 2, 3])], 'shot.png', { type: 'image/png' });
    fireEvent.change(screen.getByTestId('image-picker'), { target: { files: [file] } });
    await waitFor(() =>
      expect(getMarkdown(editor!)).toContain('90-meta/assets/jots/2026/06/stub-x.jpg'),
    );
  });
});

describe('page body styles (A7)', () => {
  // jsdom applies stylesheet rules to getComputedStyle; inject the real
  // styles.css (read from disk: vitest strips CSS imports, even `?raw`) so
  // the page overrides are checked against A1's block rules.
  const stylesCss = readFileSync(resolve(__dirname, '../styles.css'), 'utf8');
  let sheet: HTMLStyleElement;
  beforeEach(() => {
    sheet = document.createElement('style');
    sheet.textContent = stylesCss;
    document.head.appendChild(sheet);
  });
  afterEach(() => sheet.remove());

  it('gives callouts inside the page their 16px padding over A1\'s', () => {
    render(<RichMarkdownEditor markdown={'> [!info] Heads up\n> body text'} onSave={() => {}} jotId="t" />);
    const callout = screen.getByTestId('page-canvas').querySelector('.gb-callout') as HTMLElement | null;
    expect(callout).not.toBeNull();
    const cs = getComputedStyle(callout!);
    expect(cs.paddingTop).toBe('10px');
    expect(cs.paddingLeft).toBe('16px');
    expect(cs.marginBottom).toBe('1.1em');
  });

  it('gives the table of contents its 16px padding over A1\'s', () => {
    render(<RichMarkdownEditor markdown={'```toc\n```\n\n# One'} onSave={() => {}} jotId="t" />);
    const toc = screen.getByTestId('page-canvas').querySelector('.gb-toc') as HTMLElement | null;
    expect(toc).not.toBeNull();
    expect(getComputedStyle(toc!).paddingLeft).toBe('16px');
    expect(getComputedStyle(toc!).marginBottom).toBe('1.1em');
  });

  it('keeps C2 live query results compact inside the page body', () => {
    // The query view's DOM (query-view.ts) inside the page body: the page's
    // element rules (ul/li/p/pre) must not restyle the query block. jsdom
    // cascades by source order only (no specificity), so this pins the order;
    // the `.gb-prose .gb-query-*` selectors (0,2,0+) win by specificity too.
    const host = document.createElement('div');
    host.innerHTML = `
      <div class="gb-page"><div class="gb-prose gb-page-body"><div class="ProseMirror">
        <div class="gb-query">
          <div class="gb-query-results">
            <ul class="gb-query-list"><li class="gb-query-row">row</li></ul>
            <p class="gb-query-status">no matching notes</p>
            <div class="gb-query-error"><p>bad</p><pre>at line 1</pre></div>
          </div>
          <pre><code class="language-query">type: action_item</code></pre>
        </div>
      </div></div></div>`;
    document.body.appendChild(host);
    try {
      const list = getComputedStyle(host.querySelector('.gb-query-list')!);
      expect(list.marginLeft).toBe('0px');
      expect(list.marginBottom).toBe('0px');
      expect(getComputedStyle(host.querySelector('.gb-query-row')!).marginTop).toBe('0px');
      const status = getComputedStyle(host.querySelector('.gb-query-status')!);
      expect(status.marginTop).toBe('4px');
      expect(status.marginBottom).toBe('0px');
      expect(getComputedStyle(host.querySelector('.gb-query-error p')!).marginBottom).toBe('0px');
      expect(getComputedStyle(host.querySelector('.gb-query-error pre')!).marginTop).toBe('6px');
      expect(getComputedStyle(host.querySelector('.gb-query > pre')!).marginBottom).toBe('0px');
    } finally {
      host.remove();
    }
  });

  it('paints query blocks with a defined surface token', () => {
    // `--vellum` is not a token (the surface is `--bg-vellum`); an undefined
    // var leaves the query block and its menu transparent.
    expect(stylesCss).not.toContain('var(--vellum)');
  });
});
