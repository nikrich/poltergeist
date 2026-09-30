import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const manifest = JSON.parse(readFileSync(new URL('../../manifest.json', import.meta.url), 'utf-8'));

describe('manifest', () => {
  it('satisfies the app manifest contract', () => {
    expect(manifest.id).toMatch(/^[a-z][a-z0-9-]{1,31}$/);
    expect(manifest.name.length).toBeGreaterThan(0);
    expect(manifest.name.length).toBeLessThanOrEqual(64);
    expect(manifest.apiVersion).toBe(1);
    expect(manifest.icon).toMatch(/^[a-z0-9-]+$/);
    expect(manifest.entry.main).toMatch(/\.cjs$/);
    expect(manifest.entry.renderer).toMatch(/\.mjs$/);
    expect(manifest.description.length).toBeLessThanOrEqual(500);
  });
});
