import { describe, it, expect } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { resolvePluginPath } from '../protocol';

const root = mkdtempSync(join(tmpdir(), 'gb-proto-'));
mkdirSync(join(root, 'dist'), { recursive: true });
writeFileSync(join(root, 'dist', 'renderer.mjs'), 'export {}');
writeFileSync(join(root, 'top.css'), '');

describe('resolvePluginPath', () => {
  it('resolves a normal nested file', () => {
    expect(resolvePluginPath(root, 'dist/renderer.mjs')).toBe(join(root, 'dist/renderer.mjs'));
    expect(resolvePluginPath(root, 'top.css')).toBe(join(root, 'top.css'));
  });

  it('rejects .. traversal', () => {
    expect(resolvePluginPath(root, '../outside.txt')).toBeNull();
    expect(resolvePluginPath(root, 'dist/../../outside.txt')).toBeNull();
  });

  it('rejects absolute paths', () => {
    expect(resolvePluginPath(root, '/etc/passwd')).toBeNull();
  });

  it('rejects decoded dot-dot smuggling', () => {
    // caller decodes URL components before calling; simulate the decoded form
    expect(resolvePluginPath(root, '..%2F'.replace('%2F', '/'))).toBeNull();
  });

  it('rejects symlinks escaping the plugin dir', () => {
    symlinkSync('/etc', join(root, 'esc'));
    expect(resolvePluginPath(root, 'esc/passwd')).toBeNull();
  });

  it('rejects missing files', () => {
    expect(resolvePluginPath(root, 'dist/nope.mjs')).toBeNull();
  });
});
