import type { Editor } from '@tiptap/core';
import type { Node as PMNode } from '@tiptap/pm/model';
import type { NodeView } from '@tiptap/pm/view';
import type { VaultQueryResponse, VaultQueryRow } from '../../../shared/api-types';
import { ApiError } from '../api/client';
import { emitGb } from './events';
import { runVaultQuery, setNoteStatus } from './query-api';
import { freezeMarkdown, isClosedStatus } from './query-format';

export const QUERY_POLL_MS = 60_000;
export const QUERY_EDIT_DEBOUNCE_MS = 500;
export const QUERY_INDEX_RETRY_MS = 2_000;
export const QUERY_INDEX_RETRIES = 5;

type Phase =
  | { kind: 'loading' }
  | { kind: 'ready'; data: VaultQueryResponse; source: string }
  | { kind: 'unavailable' };

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(className: string, text: string, ariaLabel?: string): HTMLButtonElement {
  const b = el('button', className, text);
  b.type = 'button';
  if (ariaLabel) b.setAttribute('aria-label', ariaLabel);
  return b;
}

function isResponse(value: unknown): value is VaultQueryResponse {
  if (!value || typeof value !== 'object') return false;
  const v = value as Partial<VaultQueryResponse>;
  return Array.isArray(v.results) && Array.isArray(v.diagnostics);
}

/**
 * Live view for a ```query``` code block (smart templates C2). The fence text
 * stays the source of truth (contentDOM); results live in non-editable chrome.
 * Fetch: deferred on mount (a throwaway probe editor never fetches), on window
 * focus, every QUERY_POLL_MS while on screen, after edits, after ticks.
 */
export function createQueryView(initial: PMNode, editor: Editor, getPos: unknown): NodeView {
  let node = initial;
  let editing = node.textContent.trim() === '';
  let phase: Phase = { kind: 'loading' };
  let notice: string | null = null;
  let menuOpen = false;
  let seq = 0;
  let destroyed = false;
  let indexRetries = 0;
  let visible = true;
  let editTimer: ReturnType<typeof setTimeout> | null = null;
  const timers = new Set<ReturnType<typeof setTimeout>>();
  const busy = new Set<string>();

  const dom = el('div', 'gb-query');
  const bar = el('div', 'gb-query-bar');
  bar.contentEditable = 'false';
  const refreshBtn = button('gb-query-btn', '↻', 'refresh query');
  const menuBtn = button('gb-query-btn', '⋯', 'query options');
  menuBtn.setAttribute('aria-haspopup', 'menu');
  const menu = el('div', 'gb-query-menu');
  menu.setAttribute('role', 'menu');
  const editItem = button('gb-query-menuitem', 'edit query');
  editItem.setAttribute('role', 'menuitem');
  const freezeItem = button('gb-query-menuitem', 'freeze');
  freezeItem.setAttribute('role', 'menuitem');
  menu.append(editItem, freezeItem);
  bar.append(el('span', 'gb-query-label', 'live query'), refreshBtn, menuBtn, menu);
  const results = el('div', 'gb-query-results');
  results.contentEditable = 'false';
  const pre = el('pre');
  const code = el('code', 'language-query');
  pre.appendChild(code);
  dom.append(bar, results, pre);

  const later = (fn: () => void, ms: number): void => {
    const t = setTimeout(() => {
      timers.delete(t);
      fn();
    }, ms);
    timers.add(t);
  };

  function canWrite(): boolean {
    return editor.isEditable;
  }

  // Results must be for the text on screen: not while an edit's refresh is
  // still debouncing or in flight.
  function canFreeze(): boolean {
    return (
      canWrite() &&
      editTimer === null &&
      phase.kind === 'ready' &&
      phase.source === node.textContent &&
      !phase.data.diagnostics.some((d) => d.severity === 'error')
    );
  }

  function paintChrome(): void {
    dom.dataset.editing = String(editing);
    editItem.textContent = editing ? 'done editing' : 'edit query';
    menu.hidden = !menuOpen;
    menuBtn.setAttribute('aria-expanded', String(menuOpen));
    freezeItem.disabled = !canFreeze();
  }

  function rowEl(row: VaultQueryRow): HTMLElement {
    const li = el('li', 'gb-query-row');
    const done = isClosedStatus(row.status);
    const box = el('input');
    box.type = 'checkbox';
    box.checked = done;
    box.setAttribute('aria-label', `mark ${row.title} ${done ? 'open' : 'done'}`);
    box.disabled = !canWrite() || busy.has(row.path);
    // `click` rather than `change`: it fires after the toggle (mouse and Space
    // alike), and jsdom only fires `change` for checkboxes in the document.
    box.addEventListener('click', () => void toggle(row, box.checked));
    const link = button('gb-query-link', row.title);
    link.addEventListener('click', (e) => {
      e.preventDefault();
      emitGb(editor, 'gb:query:open', { path: row.path });
    });
    const meta = el('span', 'gb-query-meta', [row.context, row.created?.slice(0, 10) ?? ''].filter(Boolean).join(' · '));
    li.append(box, link, meta);
    if (row.snippet) li.appendChild(el('div', 'gb-query-snippet', row.snippet));
    return li;
  }

  function paint(): void {
    paintChrome();
    const parts: HTMLElement[] = [];
    if (phase.kind === 'loading') {
      parts.push(el('p', 'gb-query-status', 'loading…'));
    } else if (phase.kind === 'unavailable') {
      const chip = button('gb-query-chip', 'results unavailable — retry');
      chip.addEventListener('click', (e) => {
        e.preventDefault();
        indexRetries = 0;
        void refresh();
      });
      parts.push(chip);
    } else {
      const { data } = phase;
      const errors = data.diagnostics.filter((d) => d.severity === 'error');
      if (errors.length > 0) {
        const box = el('div', 'gb-query-error');
        box.setAttribute('role', 'alert');
        for (const d of errors) box.appendChild(el('p', undefined, `line ${d.line}: ${d.message}`));
        box.appendChild(el('pre', undefined, node.textContent));
        parts.push(box);
      } else {
        for (const d of data.diagnostics) parts.push(el('p', 'gb-query-warning', d.message));
        if (data.results.length === 0) {
          parts.push(el('p', 'gb-query-status', 'no matching notes'));
        } else {
          const list = el('ul', 'gb-query-list');
          for (const row of data.results) list.appendChild(rowEl(row));
          parts.push(list);
        }
        if (data.partial) parts.push(el('p', 'gb-query-status', 'showing the first matches only — narrow the query'));
      }
    }
    if (notice) {
      const n = el('p', 'gb-query-notice', notice);
      n.setAttribute('role', 'status');
      parts.push(n);
    }
    results.replaceChildren(...parts);
  }

  async function refresh(): Promise<void> {
    if (destroyed) return;
    const mine = ++seq;
    let next: Phase;
    let retry = false;
    const source = node.textContent;
    try {
      const data: unknown = await runVaultQuery(source);
      if (!isResponse(data)) {
        next = { kind: 'unavailable' };
      } else if (data.indexing) {
        next = { kind: 'unavailable' };
        retry = indexRetries < QUERY_INDEX_RETRIES;
      } else {
        indexRetries = 0;
        next = { kind: 'ready', data, source };
      }
    } catch {
      next = { kind: 'unavailable' };
    }
    if (destroyed || mine !== seq) return; // superseded by a newer request
    phase = next;
    paint();
    if (retry) {
      indexRetries += 1;
      later(() => void refresh(), QUERY_INDEX_RETRY_MS);
    }
  }

  async function toggle(row: VaultQueryRow, done: boolean): Promise<void> {
    if (!canWrite() || busy.has(row.path)) return;
    busy.add(row.path);
    notice = null;
    paint();
    try {
      await setNoteStatus(row.path, done ? 'done' : 'open', row.etag);
    } catch (err) {
      notice =
        err instanceof ApiError && err.status === 409
          ? `${row.title} changed elsewhere — list refreshed, try again`
          : `could not update ${row.title}: ${err instanceof Error ? err.message : String(err)}`;
    } finally {
      busy.delete(row.path);
    }
    await refresh();
  }

  function freeze(): void {
    if (!canFreeze() || phase.kind !== 'ready') return;
    const pos = typeof getPos === 'function' ? (getPos as () => number | undefined)() : undefined;
    if (typeof pos !== 'number') return;
    // tiptap-markdown parses a string passed to insertContentAt as markdown.
    // insertContentAt defaults to preserveWhitespace 'full', which would keep
    // the space after each task checkbox as leading text ("- [ ]  [[…").
    editor.commands.insertContentAt(
      { from: pos, to: pos + node.nodeSize },
      freezeMarkdown(phase.data.results),
      { parseOptions: { preserveWhitespace: false } },
    );
  }

  refreshBtn.addEventListener('click', (e) => {
    e.preventDefault();
    void refresh();
  });
  menuBtn.addEventListener('click', (e) => {
    e.preventDefault();
    menuOpen = !menuOpen;
    paintChrome();
  });
  editItem.addEventListener('click', (e) => {
    e.preventDefault();
    editing = !editing;
    menuOpen = false;
    paintChrome();
  });
  freezeItem.addEventListener('click', (e) => {
    e.preventDefault();
    menuOpen = false;
    paintChrome();
    freeze();
  });

  const onFocus = (): void => void refresh();
  window.addEventListener('focus', onFocus);
  const poll = setInterval(() => {
    if (visible && document.visibilityState !== 'hidden') void refresh();
  }, QUERY_POLL_MS);
  const observer =
    typeof IntersectionObserver === 'undefined'
      ? null
      : new IntersectionObserver((entries) => {
          visible = entries.some((entry) => entry.isIntersecting);
        });
  observer?.observe(dom);

  paint();
  later(() => void refresh(), 0);

  return {
    dom,
    contentDOM: code,
    update(next) {
      if (next.type !== node.type || next.attrs.language !== 'query') return false;
      const changed = next.textContent !== node.textContent;
      node = next;
      if (changed) {
        if (editTimer) clearTimeout(editTimer);
        editTimer = setTimeout(() => {
          editTimer = null;
          void refresh();
        }, QUERY_EDIT_DEBOUNCE_MS);
        paintChrome(); // freeze is off until the edited query's results load
      }
      return true;
    },
    stopEvent: (event) => {
      const t = event.target as globalThis.Node | null;
      return !!t && (bar.contains(t) || results.contains(t));
    },
    ignoreMutation: (mutation) =>
      mutation.type !== 'selection' && !code.contains(mutation.target as globalThis.Node),
    destroy() {
      destroyed = true;
      seq++;
      if (editTimer) clearTimeout(editTimer);
      for (const t of timers) clearTimeout(t);
      timers.clear();
      clearInterval(poll);
      window.removeEventListener('focus', onFocus);
      observer?.disconnect();
    },
  };
}
