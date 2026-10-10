import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ...actual, get: vi.fn() };
});

import { get } from '../lib/api/client';
import { openWikilink, resolveBareWikilink } from '../lib/open-wikilink';
import { toast } from '../stores/toast';

const getMock = vi.mocked(get);

beforeEach(() => {
  getMock.mockReset();
  vi.restoreAllMocks();
});

describe('openWikilink', () => {
  it('opens path-form links at once, without asking the index', () => {
    const open = vi.fn();
    openWikilink('20-contexts/work/a#Plan', open);
    expect(open).toHaveBeenCalledWith('20-contexts/work/a.md');
    expect(getMock).not.toHaveBeenCalled();
  });

  it('resolves a bare name to the note the index finds', async () => {
    getMock.mockResolvedValue({ path: '20-contexts/work/Beta.md', exists: true, indexing: false });
    const open = vi.fn();
    openWikilink('Beta#Plan', open);
    await vi.waitFor(() => expect(open).toHaveBeenCalledWith('20-contexts/work/Beta.md'));
    expect(getMock).toHaveBeenCalledWith('/v1/vault/resolve?target=Beta');
  });

  it('says an unwritten page is not written yet instead of opening a 404', async () => {
    getMock.mockResolvedValue({ path: 'Someday Idea.md', exists: false, indexing: false });
    const info = vi.spyOn(toast, 'info');
    const open = vi.fn();
    openWikilink('Someday Idea', open);
    await vi.waitFor(() => expect(info).toHaveBeenCalledWith('“Someday Idea” isn\'t written yet'));
    expect(open).not.toHaveBeenCalled();
  });

  it('ignores an empty target', () => {
    const open = vi.fn();
    openWikilink('  ', open);
    expect(open).not.toHaveBeenCalled();
  });
});

describe('resolveBareWikilink', () => {
  it('falls back to <name>.md while the index is cold', async () => {
    getMock.mockResolvedValue({ path: 'Beta.md', exists: false, indexing: true });
    expect(await resolveBareWikilink('Beta')).toEqual({ kind: 'open', path: 'Beta.md' });
  });

  it('falls back on an error', async () => {
    getMock.mockRejectedValue(new Error('sidecar down'));
    expect(await resolveBareWikilink('Beta')).toEqual({ kind: 'open', path: 'Beta.md' });
  });

  it('falls back on a timeout', async () => {
    getMock.mockReturnValue(new Promise(() => {}));
    expect(await resolveBareWikilink('Beta', 10)).toEqual({ kind: 'open', path: 'Beta.md' });
  });
});
