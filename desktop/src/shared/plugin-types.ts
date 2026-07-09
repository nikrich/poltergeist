import { z } from 'zod';

// A plugin is a directory: manifest.json + pre-built dist/ entries. Trusted
// code — main.cjs runs unsandboxed in the main process. See
// docs/superpowers/specs/2026-07-06-plugin-system-design.md.
export const manifestSchema = z.object({
  id: z.string().regex(/^[a-z][a-z0-9-]{1,31}$/),
  name: z.string().min(1).max(64),
  version: z.string().min(1),
  description: z.string().max(500).optional(),
  apiVersion: z.literal(1),
  icon: z
    .string()
    .regex(/^[a-z0-9-]+$/)
    .optional(),
  entry: z
    .object({
      main: z
        .string()
        .regex(/^[\w./-]+\.cjs$/)
        .optional(),
      renderer: z
        .string()
        .regex(/^[\w./-]+\.mjs$/)
        .optional(),
    })
    .refine((e) => e.main || e.renderer, {
      message: 'entry needs main and/or renderer',
    }),
});

export type PluginManifest = z.infer<typeof manifestSchema>;

export type PluginRuntimeState = 'enabled' | 'disabled' | 'errored' | 'invalid';

export interface PluginRecord {
  /** Manifest id, or the directory name when the manifest is invalid. */
  id: string;
  dir: string;
  manifest: PluginManifest | null;
  state: PluginRuntimeState;
  error?: string;
}

/** What the renderer needs to show sidebar entries and mount plugin UIs. */
export interface ActivePluginInfo {
  id: string;
  name: string;
  icon: string;
  hasRenderer: boolean;
  rendererEntry: string | null;
}

// Public marketplace registry — schema owned by market.getpoltergeist.com,
// not this repo. Tolerant of unknown extra fields (zod strips by default).
export const marketplaceEntrySchema = z.object({
  id: z.string(),
  name: z.string(),
  version: z.string(),
  description: z.string().optional(),
  icon: z.string().optional(),
  author: z.string().optional(),
  tags: z.array(z.string()).optional(),
  repo: z.string(),
  subdir: z.string().optional(),
  ref: z.string().optional(),
  download: z.string().optional(),
});

export type MarketplaceEntry = z.infer<typeof marketplaceEntrySchema>;

export const registrySchema = z.object({
  apiVersion: z.literal(1),
  generatedAt: z.string(),
  plugins: z.array(marketplaceEntrySchema),
});

export type MarketplaceRegistry = z.infer<typeof registrySchema>;
