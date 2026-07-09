import { isNewerVersion, marketplaceRepoUrl } from './registry';
import type { MarketplaceEntry, MarketplaceListing, PluginRecord } from '../../shared/plugin-types';

type Result = { ok: true } | { ok: false; error: string };
type ListResult = MarketplaceListing[] | { ok: false; error: string };

function err(e: unknown): { ok: false; error: string } {
  return { ok: false, error: e instanceof Error ? e.message : String(e) };
}

/**
 * The marketplace orchestrator, factored as a pure function over injected
 * deps so it is unit-testable without electron or network access (mirrors
 * makeSidecarHandler above).
 */
export function makeMarketplaceHandlers(deps: {
  fetchRegistry: () => Promise<MarketplaceEntry[]>;
  records: () => PluginRecord[];
  installFromGit: (url: string, subdir: string | undefined, root: string) => Promise<unknown>;
  updateFromGit: (
    url: string,
    subdir: string | undefined,
    id: string,
    root: string,
  ) => Promise<unknown>;
  reload: () => Promise<void>;
  pluginsRoot: string;
}) {
  async function list(): Promise<ListResult> {
    let entries: MarketplaceEntry[];
    try {
      entries = await deps.fetchRegistry();
    } catch (e) {
      return err(e);
    }
    const records = deps.records();
    return entries.map((entry) => {
      const record = records.find((r) => r.id === entry.id && r.manifest);
      const installedVersion = record?.manifest?.version ?? null;
      return {
        ...entry,
        installed: installedVersion !== null,
        installedVersion,
        updateAvailable: installedVersion !== null && isNewerVersion(entry.version, installedVersion),
      };
    });
  }

  async function install(id: string): Promise<Result> {
    try {
      const entries = await deps.fetchRegistry();
      const entry = entries.find((e) => e.id === id);
      if (!entry) throw new Error(`unknown marketplace plugin: ${id}`);
      const url = marketplaceRepoUrl(entry);
      await deps.installFromGit(url, entry.subdir || undefined, deps.pluginsRoot);
      await deps.reload();
      return { ok: true };
    } catch (e) {
      return err(e);
    }
  }

  async function update(id: string): Promise<Result> {
    try {
      const entries = await deps.fetchRegistry();
      const entry = entries.find((e) => e.id === id);
      if (!entry) throw new Error(`unknown marketplace plugin: ${id}`);
      const installed = deps.records().some((r) => r.id === id && r.manifest);
      if (!installed) throw new Error(`plugin "${id}" is not installed`);
      const url = marketplaceRepoUrl(entry);
      await deps.updateFromGit(url, entry.subdir || undefined, id, deps.pluginsRoot);
      await deps.reload();
      return { ok: true };
    } catch (e) {
      return err(e);
    }
  }

  return { list, install, update };
}
