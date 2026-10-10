import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { VaultQueryRow } from '../../shared/api-types';
import { freezeMarkdown, frozenItem, isClosedStatus } from '../lib/editor/query-format';
import { runVaultQuery, setNoteStatus } from '../lib/editor/query-api';

function row(over: Partial<VaultQueryRow> = {}): VaultQueryRow {
  return {
    path: '20-contexts/work/a.md',
    title: 'Send Alex the budget',
    context: 'work',
    status: null,
    created: '2026-10-08T09:00:00+00:00',
    snippet: '',
    etag: 'aaaaaaaaaaaaaaaa',
    ...over,
  };
}

describe('isClosedStatus', () => {
  it('treats done and closed (any case) as closed, everything else as open', () => {
    expect(isClosedStatus('done')).toBe(true);
    expect(isClosedStatus('Closed')).toBe(true);
    expect(isClosedStatus('open')).toBe(false);
    expect(isClosedStatus('blocked')).toBe(false);
    expect(isClosedStatus(null)).toBe(false);
  });
});

describe('freezeMarkdown', () => {
  it('writes one task item per row with a titled wikilink', () => {
    expect(freezeMarkdown([row(), row({ path: '20-contexts/work/b.md', title: 'Book the room', status: 'done' })])).toBe(
      '- [ ] [[20-contexts/work/a|Send Alex the budget]]\n- [x] [[20-contexts/work/b|Book the room]]',
    );
  });

  it('turns brackets and pipes in titles into spaces', () => {
    expect(frozenItem(row({ title: 'Plan [draft] | v2' }))).toBe('- [ ] [[20-contexts/work/a|Plan draft v2]]');
  });

  it('uses a bare link when the title is empty or the target itself', () => {
    expect(frozenItem(row({ title: '[]' }))).toBe('- [ ] [[20-contexts/work/a]]');
    expect(frozenItem(row({ title: '20-contexts/work/a' }))).toBe('- [ ] [[20-contexts/work/a]]');
  });

  it('says no matching notes for zero rows', () => {
    expect(freezeMarkdown([])).toBe('no matching notes');
  });
});

describe('query-api', () => {
  const apiRequest = vi.fn();
  beforeEach(() => {
    apiRequest.mockReset();
    window.gb = { ...window.gb, api: { request: apiRequest } } as typeof window.gb;
  });

  it('posts the block text to /v1/vault/query', async () => {
    const data = { results: [], diagnostics: [], indexing: false, partial: false };
    apiRequest.mockResolvedValue({ ok: true, data });
    await expect(runVaultQuery('type: action_item')).resolves.toEqual(data);
    expect(apiRequest).toHaveBeenCalledWith('POST', '/v1/vault/query', { query: 'type: action_item' });
  });

  it('patches the status with If-Match when there is an etag', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: { path: 'a.md', status: 'done', etag: 'bbbbbbbbbbbbbbbb' } });
    await setNoteStatus('a.md', 'done', 'aaaaaaaaaaaaaaaa');
    expect(apiRequest).toHaveBeenCalledWith(
      'PATCH',
      '/v1/vault/status',
      { path: 'a.md', status: 'done' },
      { ifMatch: 'aaaaaaaaaaaaaaaa' },
    );
  });

  it('sends no If-Match without an etag', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: { path: 'a.md', status: 'open', etag: null } });
    await setNoteStatus('a.md', 'open', null);
    expect(apiRequest.mock.calls[0]).toHaveLength(3);
  });
});
