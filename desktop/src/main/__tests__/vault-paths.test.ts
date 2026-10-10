import { describe, expect, it } from 'vitest';
import { isInsideVault } from '../vault-paths';

describe('isInsideVault', () => {
  it('accepts paths inside, including trailing-slash vault', () => {
    expect(isInsideVault('/tmp/vault', '/tmp/vault/a/b.pdf')).toBe(true);
    expect(isInsideVault('/tmp/vault/', '/tmp/vault/a.pdf')).toBe(true);
  });
  it('rejects traversal and sibling prefixes', () => {
    expect(isInsideVault('/tmp/vault', '/tmp/vault/../x')).toBe(false);
    expect(isInsideVault('/tmp/vault', '/tmp/vault/../../etc/passwd')).toBe(false);
    expect(isInsideVault('/tmp/vault', '/tmp/vault-other/x')).toBe(false);
  });
  it('root is allowed only when allowRoot', () => {
    expect(isInsideVault('/tmp/vault', '/tmp/vault')).toBe(true);
    expect(isInsideVault('/tmp/vault', '/tmp/vault', { allowRoot: false })).toBe(false);
  });
});
