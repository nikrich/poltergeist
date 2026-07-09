import type { RegistryEntry } from './registry';
import type { PluginRecord } from '../../shared/plugin-types';

// Marketplace backend logic, factored as a pure factory over injected deps so
// it is unit-testable without electron or network — mirrors makeSidecarHandler
// in ./ipc. The IPC layer (installPluginsIpc) wires the real
// fetchRegistry/searchEntries/installFromGit/updateFromGit into this.

type Result = { ok: true } | { ok: false; error: string };

type GitInstall = (
  url: string,
  subdir: string | undefined,
  pluginsRoot: string,
  ref?: string,
) => Promise<PluginRecord>;

export interface MarketplaceDeps {
  fetchRegistry: () => Promise<RegistryEntry[]>;
  searchEntries: (entries: RegistryEntry[], query: string) => RegistryEntry[];
  installFromGit: GitInstall;
  updateFromGit: GitInstall;
  pluginsRoot: string;
}

export interface MarketplaceHandlers {
  list(): Promise<RegistryEntry[]>;
  search(query: string): Promise<RegistryEntry[]>;
  install(id: string): Promise<Result>;
  update(id: string): Promise<Result>;
}

export function makeMarketplaceHandlers(deps: MarketplaceDeps): MarketplaceHandlers {
  const gitUrl = (entry: RegistryEntry): string => `https://github.com/${entry.repo}.git`;

  async function run(id: string, install: GitInstall): Promise<Result> {
    try {
      const entries = await deps.fetchRegistry();
      const entry = entries.find((e) => e.id === id);
      if (!entry) return { ok: false, error: `plugin "${id}" not found in registry` };
      await install(gitUrl(entry), entry.subdir || undefined, deps.pluginsRoot, entry.ref || undefined);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : String(e) };
    }
  }

  return {
    list: () => deps.fetchRegistry(),
    search: async (query) => deps.searchEntries(await deps.fetchRegistry(), query),
    install: (id) => run(id, deps.installFromGit),
    update: (id) => run(id, deps.updateFromGit),
  };
}
