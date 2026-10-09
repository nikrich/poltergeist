import { describe, expect, it, vi } from 'vitest';
import { resolve } from 'node:path';

vi.mock('electron', () => ({ protocol: { handle: vi.fn() }, net: { fetch: vi.fn() } }));

import { resolveDocPath } from '../doc-protocol';

const V = '/tmp/vault';

describe('resolveDocPath', () => {
  it('allows files inside context and project docs roots', () => {
    expect(resolveDocPath(V, '20-contexts/work/docs/a.pdf')).toBe(resolve(V, '20-contexts/work/docs/a.pdf'));
    expect(resolveDocPath(V, '20-contexts/work/projects/pay/docs/specs/a b.pdf')).toBe(
      resolve(V, '20-contexts/work/projects/pay/docs/specs/a b.pdf'),
    );
  });

  it('rejects anything outside a docs root', () => {
    for (const rel of [
      '20-contexts/work/note.md',
      '90-meta/projects.json',
      '20-contexts/work/docs/../secret.md',
      '20-contexts/work/docs/./a.pdf',
      '/etc/passwd',
      '20-contexts/work/projects/pay/other/a.pdf',
      '20-contexts/work/docs',
    ]) {
      expect(resolveDocPath(V, rel)).toBeNull();
    }
  });
});

import { docPathFromUrl } from '../doc-protocol';

describe('docPathFromUrl', () => {
  it('decodes and resolves', () => {
    expect(docPathFromUrl(V, 'gbdoc://doc/20-contexts/work/docs/a%20b.pdf')).toBe(
      resolve(V, '20-contexts/work/docs/a b.pdf'),
    );
  });
  it('returns bad-request on malformed escapes', () => {
    expect(docPathFromUrl(V, 'gbdoc://doc/20-contexts/work/docs/%E0%A4.pdf')).toBe('bad-request');
  });
  it('returns null for forbidden paths, incl. encoded traversal', () => {
    expect(docPathFromUrl(V, 'gbdoc://doc/90-meta/projects.json')).toBeNull();
    expect(docPathFromUrl(V, 'gbdoc://doc/20-contexts/work/docs/%2e%2e/x.md')).toBeNull();
  });
});
