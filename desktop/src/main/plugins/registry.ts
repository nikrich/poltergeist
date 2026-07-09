import { registrySchema, type MarketplaceEntry } from '../../shared/plugin-types';

export const REGISTRY_URL = 'https://market.getpoltergeist.com/registry.json';
export const MARKET_BASE = 'https://market.getpoltergeist.com';

export async function fetchRegistry(
  fetchImpl: typeof fetch = fetch,
): Promise<MarketplaceEntry[]> {
  const res = await fetchImpl(REGISTRY_URL);
  if (!res.ok) {
    throw new Error(`failed to fetch marketplace registry: HTTP ${res.status}`);
  }
  const body = await res.json();
  const parsed = registrySchema.safeParse(body);
  if (!parsed.success) {
    throw new Error(`invalid marketplace registry: ${parsed.error.issues[0]?.message ?? 'validation failed'}`);
  }
  return parsed.data.plugins;
}

function versionSegments(version: string): number[] {
  return version.split('.').map((s) => {
    const n = Number.parseInt(s, 10);
    return Number.isFinite(n) ? n : 0;
  });
}

export function isNewerVersion(candidate: string, installed: string): boolean {
  const a = versionSegments(candidate);
  const b = versionSegments(installed);
  const len = Math.max(a.length, b.length);
  for (let i = 0; i < len; i++) {
    const av = a[i] ?? 0;
    const bv = b[i] ?? 0;
    if (av !== bv) return av > bv;
  }
  return false;
}

const FULL_URL = /^(https:\/\/|git@)/;

export function marketplaceRepoUrl(entry: { repo: string }): string {
  if (FULL_URL.test(entry.repo)) return entry.repo;
  return `https://github.com/${entry.repo}.git`;
}
