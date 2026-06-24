import { describe, it, expect } from 'vitest';
import { join } from 'node:path';
import { assetVaultRelPath, resolveAssetPath } from '../assets';

describe('assetVaultRelPath', () => {
  it('builds a dated, slug-safe vault-relative path', () => {
    const p = assetVaultRelPath('abc123def', 'jpg', 'x9z2', new Date('2026-06-24T14:32:00Z'));
    expect(p).toBe('90-meta/assets/jots/2026/06/abc123def-x9z2.jpg');
  });
});

describe('resolveAssetPath', () => {
  const vault = '/vault';
  it('resolves a path inside the asset dir', () => {
    expect(resolveAssetPath(vault, '90-meta/assets/jots/2026/06/a-1.jpg')).toBe(
      join(vault, '90-meta/assets/jots/2026/06/a-1.jpg'),
    );
  });
  it('rejects traversal outside the asset dir', () => {
    expect(resolveAssetPath(vault, '90-meta/assets/../../secrets.md')).toBeNull();
    expect(resolveAssetPath(vault, '../secrets.md')).toBeNull();
    expect(resolveAssetPath(vault, '/etc/passwd')).toBeNull();
  });
});
