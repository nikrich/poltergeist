import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Editor } from '@tiptap/core';
import { SuggestionPluginKey } from '@tiptap/suggestion';
import * as client from '../lib/api/client';
import { makeEditor } from './helpers/editor';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);

/** Suggestion plugins by trigger: slash uses Suggestion's default key, A2's use `cfg.name`. */
const TRIGGERS = [
  { name: 'slash', typed: '/' },
  { name: 'wikilinkSuggest', typed: 'see [[' },
  { name: 'tagSuggest', typed: 'plan #ro' },
  { name: 'personSuggest', typed: 'met @al' },
] as const;

function isActive(e: Editor, name: string): boolean {
  if (name === 'slash') return Boolean(SuggestionPluginKey.getState(e.state)?.active);
  const keyOf = (p: { spec: { key?: unknown } }) => (p.spec.key as { key?: string } | undefined)?.key ?? '';
  const plugin = e.state.plugins.find((p) => new RegExp(`^${name}\\$\\d*$`).test(keyOf(p)));
  if (!plugin) throw new Error(`no plugin ${name}`);
  return Boolean((plugin.getState(e.state) as { active?: boolean } | undefined)?.active);
}

afterEach(() => {
  document.body.innerHTML = '';
  getMock.mockReset();
});

describe('slash and link suggestion triggers coexist', () => {
  it.each(TRIGGERS)('$typed activates only the $name suggestion', async ({ name, typed }) => {
    getMock.mockResolvedValue({ items: [], indexing: false });
    const e = makeEditor('');
    e.chain().focus().insertContent({ type: 'text', text: typed }).run();
    const active = TRIGGERS.map((t) => t.name).filter((n) => isActive(e, n));
    expect(active).toEqual([name]);
    await new Promise((r) => setTimeout(r, 0)); // let pending items() settle before teardown
  });
});
