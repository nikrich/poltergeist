import { z } from 'zod';
import type { RegistryEntry } from '../../shared/plugin-types';

// Marketplace registry client. Lives in the main process because the
// renderer CSP (src/renderer/index.html, connect-src 'self' plugin:) blocks
// direct fetches to market.getpoltergeist.com — see
// src/renderer/__tests__/csp.test.ts. `fetch` is injected so this module is
// unit-testable without network, mirroring makeSidecarHandler in ./ipc.

export const registryEntrySchema = z.object({
  id: z.string(),
  repo: z.string(),
  subdir: z.string().optional(),
  ref: z.string().optional(),
  author: z.string().optional(),
  tags: z
    .array(z.string().regex(/^[a-z][a-z0-9-]*$/))
    .max(8)
    .optional(),
  name: z.string().optional(),
  description: z.string().optional(),
});

// RegistryEntry is defined in shared/ (see plugin-types.ts); re-exported here so
// `import { RegistryEntry } from './registry'` keeps working. The schema's
// inferred shape must stay assignable to it — this line fails to compile if the
// two drift apart.
const _schemaMatchesType: RegistryEntry = {} as z.infer<typeof registryEntrySchema>;
void _schemaMatchesType;

export type { RegistryEntry };

const DEFAULT_BASE_URL = 'https://api.github.com/repos/nikrich/poltergeist-plugins/contents/plugins';

interface ContentsEntry {
  name: string;
}

export interface FetchRegistryDeps {
  fetch: typeof globalThis.fetch;
  baseUrl?: string;
}

/**
 * Lists the registry's plugin files via the GitHub contents API, then fetches
 * and validates each entry's raw JSON. A single malformed entry is dropped,
 * not fatal.
 */
export async function fetchRegistry(deps: FetchRegistryDeps): Promise<RegistryEntry[]> {
  const baseUrl = deps.baseUrl ?? DEFAULT_BASE_URL;

  const listing = await fetchJson(deps.fetch, baseUrl);
  if (!Array.isArray(listing)) return [];

  const files = listing.filter(
    (item): item is ContentsEntry =>
      typeof item === 'object' && item !== null && typeof (item as ContentsEntry).name === 'string' && (item as ContentsEntry).name.endsWith('.json'),
  );

  const entries = await Promise.all(
    files.map(async (file) => {
      try {
        const raw = await fetchJson(deps.fetch, `${baseUrl}/${file.name}`);
        const parsed = registryEntrySchema.safeParse(raw);
        return parsed.success ? parsed.data : null;
      } catch {
        return null;
      }
    }),
  );

  return entries.filter((e): e is RegistryEntry => e !== null);
}

async function fetchJson(fetchFn: typeof globalThis.fetch, url: string): Promise<unknown> {
  const res = await fetchFn(url);
  return res.json();
}

/** Case-insensitive filter over id, name, description, and tags. */
export function searchEntries(entries: RegistryEntry[], query: string): RegistryEntry[] {
  const q = query.trim().toLowerCase();
  if (q === '') return entries;

  return entries.filter((entry) => {
    const haystacks = [entry.id, entry.name, entry.description, ...(entry.tags ?? [])];
    return haystacks.some((h) => h?.toLowerCase().includes(q));
  });
}
