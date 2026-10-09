import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { Editor } from '@tiptap/core';
import type { EditorView } from '@tiptap/pm/view';
import * as client from '../lib/api/client';
import { buildEditorExtensions } from '../lib/editor/extensions';
import { getMarkdown } from '../lib/editor/markdown';
import type { SuggestItem, SuggestResponse } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);

const ALPHA: SuggestItem = {
  kind: 'page', label: 'Alpha plan', path: '20-contexts/work/alpha-plan.md',
  context: 'work', detail: '20-contexts/work/alpha-plan', count: null,
};
const REVIEW: SuggestItem = {
  kind: 'page', label: 'The alpha review', path: '20-contexts/work/alpha-review.md',
  context: 'work', detail: '20-contexts/work/alpha-review', count: null,
};
const ALEX: SuggestItem = {
  kind: 'person', label: 'Alex', path: '30-cross-context/people/alex.md',
  context: '', detail: '30-cross-context/people/alex', count: null,
};
const ROADMAP: SuggestItem = { kind: 'tag', label: 'roadmap', path: null, context: '', detail: '3 notes', count: 3 };

function respond(byKind: Partial<Record<'page' | 'tag' | 'person', SuggestResponse | Error>>) {
  getMock.mockImplementation((async (path: string) => {
    const kind = new URL(path, 'http://x').searchParams.get('kind') as 'page' | 'tag' | 'person';
    const r = byKind[kind];
    if (!r) throw new Error(`unexpected ${path}`);
    if (r instanceof Error) throw r;
    return r;
  }) as unknown as typeof client.get);
}

let editor: Editor | null = null;

function mount(content = ''): Editor {
  const el = document.createElement('div');
  document.body.appendChild(el);
  editor = new Editor({ element: el, extensions: buildEditorExtensions(), content });
  return editor;
}

function type(e: Editor, text: string): void {
  e.chain().focus().insertContent({ type: 'text', text }).run();
}

function press(e: Editor, key: string): boolean {
  const event = new KeyboardEvent('keydown', { key });
  return Boolean(
    e.view.someProp('handleKeyDown', (f: (view: EditorView, ev: KeyboardEvent) => boolean | void) =>
      f(e.view, event),
    ),
  );
}

const tick = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  editor?.destroy();
  editor = null;
  document.body.innerHTML = '';
  getMock.mockReset();
});

describe('[[ wikilink suggestions', () => {
  it('queries pages and inserts an aliased vault-path wikilink on Enter', async () => {
    respond({ page: { items: [ALPHA, REVIEW], indexing: false } });
    const e = mount();
    type(e, 'see [[alp');
    expect(await screen.findByText('Alpha plan')).toBeInTheDocument();
    expect(screen.getByText('20-contexts/work/alpha-plan')).toBeInTheDocument();
    expect(getMock).toHaveBeenCalledWith('/v1/vault/suggest?kind=page&q=alp&limit=20');
    expect(press(e, 'Enter')).toBe(true);
    expect(getMarkdown(e).trimEnd()).toBe('see [[20-contexts/work/alpha-plan|Alpha plan]]');
    await waitFor(() => expect(screen.queryByText('Alpha plan')).toBeNull());
  });

  it('ArrowDown moves the highlight before Enter', async () => {
    respond({ page: { items: [ALPHA, REVIEW], indexing: false } });
    const e = mount();
    type(e, '[[alp');
    await screen.findByText('The alpha review');
    expect(press(e, 'ArrowDown')).toBe(true);
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /The alpha review/ })).toHaveAttribute('aria-selected', 'true'),
    );
    press(e, 'Enter');
    expect(getMarkdown(e)).toContain('[[20-contexts/work/alpha-review|The alpha review]]');
  });

  it('omits the alias inside a table cell', async () => {
    respond({ page: { items: [ALPHA], indexing: false } });
    const e = mount('| who | link |\n| --- | --- |\n| a | x |');
    let cellEnd = -1;
    e.state.doc.descendants((node, pos) => {
      if (node.isText && node.text === 'x') cellEnd = pos + 1;
    });
    e.commands.setTextSelection(cellEnd);
    type(e, '[[alp');
    await screen.findByText('Alpha plan');
    press(e, 'Enter');
    const md = getMarkdown(e);
    expect(md).toContain('x[[20-contexts/work/alpha-plan]]');
    expect(md).not.toContain('|Alpha plan');
  });

  it('shows "no suggestions" and lets Enter through when nothing matches', async () => {
    respond({ page: { items: [], indexing: false } });
    const e = mount();
    type(e, '[[zzz');
    expect(await screen.findByText('no suggestions')).toBeInTheDocument();
    press(e, 'Enter');
    expect(e.state.doc.childCount).toBe(2); // Enter reached the editor: new paragraph
    expect(getMarkdown(e)).not.toContain('[[20-');
  });

  it('shows "no suggestions" when the request fails', async () => {
    respond({ page: new Error('sidecar down') });
    const e = mount();
    type(e, '[[alp');
    expect(await screen.findByText('no suggestions')).toBeInTheDocument();
  });

  it('shows "indexing vault…" while the index builds', async () => {
    respond({ page: { items: [], indexing: true } });
    const e = mount();
    type(e, '[[alp');
    expect(await screen.findByText('indexing vault…')).toBeInTheDocument();
  });

  it('Escape closes the menu', async () => {
    respond({ page: { items: [ALPHA], indexing: false } });
    const e = mount();
    type(e, '[[alp');
    await screen.findByText('Alpha plan');
    expect(press(e, 'Escape')).toBe(true);
    await waitFor(() => expect(screen.queryByText('Alpha plan')).toBeNull());
  });

  it('does not query once the link was closed by hand', async () => {
    respond({ page: { items: [ALPHA], indexing: false } });
    const e = mount();
    type(e, '[[foo]] and more');
    await tick();
    expect(getMock).not.toHaveBeenCalled();
  });
});

describe('@ person suggestions', () => {
  it('inserts a person wikilink with an @ alias', async () => {
    respond({ person: { items: [ALEX], indexing: false } });
    const e = mount();
    type(e, 'met @al');
    await screen.findByText('Alex');
    expect(getMock).toHaveBeenCalledWith('/v1/vault/suggest?kind=person&q=al&limit=20');
    press(e, 'Enter');
    expect(getMarkdown(e).trimEnd()).toBe('met [[30-cross-context/people/alex|@Alex]]');
  });

  it('does not trigger inside an email address', async () => {
    respond({ person: { items: [ALEX], indexing: false } });
    const e = mount();
    type(e, 'mail alex@example');
    await tick();
    expect(getMock).not.toHaveBeenCalled();
  });
});

describe('# tag suggestions', () => {
  it('inserts a plain #tag', async () => {
    respond({ tag: { items: [ROADMAP], indexing: false } });
    const e = mount();
    type(e, 'plan #ro');
    await screen.findByText('#roadmap');
    expect(screen.getByText('3 notes')).toBeInTheDocument();
    press(e, 'Enter');
    expect(getMarkdown(e).trimEnd()).toBe('plan #roadmap');
  });

  it('stays closed for a bare # (heading shorthand)', async () => {
    respond({ tag: { items: [ROADMAP], indexing: false } });
    const e = mount();
    type(e, '#');
    await tick();
    expect(getMock).not.toHaveBeenCalled();
    expect(screen.queryByText('no suggestions')).toBeNull();
  });
});

describe('late results after the session ended', () => {
  function deferGet(): (r: SuggestResponse) => void {
    let release: (r: SuggestResponse) => void = () => undefined;
    const pending = new Promise<SuggestResponse>((r) => {
      release = r;
    });
    getMock.mockImplementation((() => pending) as unknown as typeof client.get);
    return release;
  }
  const settle = () => new Promise((r) => setTimeout(r, 30));

  it('does not paint a popup after the editor is destroyed', async () => {
    const release = deferGet();
    const e = mount();
    type(e, '[[alp');
    await tick();
    e.destroy();
    editor = null;
    release({ items: [ALPHA], indexing: false });
    await settle();
    expect(document.querySelector('[role=listbox]')).toBeNull();
  });

  it('does not revive the # menu after a space ended the session', async () => {
    const release = deferGet();
    const e = mount();
    type(e, 'plan #ro');
    await tick();
    type(e, ' ');
    release({ items: [ROADMAP], indexing: false });
    await settle();
    expect(document.querySelector('[role=listbox]')).toBeNull();
  });

  it('a hand-closed ] wins over an older pending fetch', async () => {
    const release = deferGet();
    const e = mount();
    type(e, '[[foo');
    await tick();
    type(e, ']');
    release({ items: [ALPHA], indexing: false });
    await settle();
    expect(document.querySelector('[role=listbox]')).toBeNull();
    press(e, 'Enter'); // must reach the editor, not pick the stale "foo" result
    expect(e.state.doc.childCount).toBe(2);
    expect(e.state.doc.textContent).toBe('[[foo]');
    expect(getMarkdown(e)).not.toContain('alpha-plan');
  });
});
