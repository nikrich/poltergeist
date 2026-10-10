import { describe, it, expect } from 'vitest';
import type { Editor } from '@tiptap/core';
import { makeEditor } from './helpers/editor';

describe('makeEditor cleanup', () => {
  let first: Editor | undefined;
  let selfDestroyed: Editor | undefined;

  it('creates a live editor', () => {
    first = makeEditor('a');
    expect(first.isDestroyed).toBe(false);
  });

  it('destroyed the previous test editor automatically', () => {
    expect(first?.isDestroyed).toBe(true);
  });

  it('tolerates a test destroying its own editor', () => {
    selfDestroyed = makeEditor('b');
    selfDestroyed.destroy();
    expect(selfDestroyed.isDestroyed).toBe(true);
  });

  it('the double destroy in teardown did not throw', () => {
    expect(selfDestroyed?.isDestroyed).toBe(true);
  });
});
