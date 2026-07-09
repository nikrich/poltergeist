import { useCallback, useEffect, useState } from 'react';
import { Panel } from '../components/Panel';
import { Btn } from '../components/Btn';
import { Pill } from '../components/Pill';
import { Lucide } from '../components/Lucide';
import { toast } from '../stores/toast';
import type { PluginRecord, RegistryEntry } from '../../shared/plugin-types';

export function MarketplaceScreen() {
  const [entries, setEntries] = useState<RegistryEntry[] | null>(null);
  const [installed, setInstalled] = useState<PluginRecord[]>([]);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);

  const fetchEntries = useCallback((q: string) => {
    const trimmed = q.trim();
    return trimmed
      ? window.gb.plugins.marketplaceSearch(trimmed)
      : window.gb.plugins.marketplaceList();
  }, []);

  const refreshInstalled = useCallback(async () => {
    setInstalled(await window.gb.plugins.list());
  }, []);

  useEffect(() => {
    void refreshInstalled();
  }, [refreshInstalled]);

  useEffect(() => {
    let alive = true;
    void fetchEntries(query).then((res) => {
      if (alive) setEntries(res);
    });
    return () => {
      alive = false;
    };
  }, [query, fetchEntries]);

  const run = useCallback(
    async (action: () => Promise<{ ok: true } | { ok: false; error: string }>) => {
      setBusy(true);
      try {
        const res = await action();
        if (!res.ok && res.error !== 'cancelled') toast.error(res.error);
        await refreshInstalled();
        setEntries(await fetchEntries(query));
      } finally {
        setBusy(false);
      }
    },
    [refreshInstalled, fetchEntries, query],
  );

  const installedIds = new Set(installed.map((r) => r.id));

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-5">
      <Panel title="marketplace" subtitle={entries ? `${entries.length}` : undefined}>
        <div className="px-1 pb-2">
          <input
            className="w-full rounded-r6 border border-hairline-2 bg-paper px-2 py-[6px] text-12 text-ink-0 outline-none placeholder:text-ink-2"
            placeholder="search plugins"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {entries === null ? (
          <div className="p-3 text-12 text-ink-2">…</div>
        ) : entries.length === 0 ? (
          <div className="p-3 text-12 text-ink-2">no plugins found.</div>
        ) : (
          entries.map((e) => {
            const isInstalled = installedIds.has(e.id);
            return (
              <div
                key={e.id}
                className="flex items-center gap-3 rounded-r6 border border-hairline bg-paper px-3 py-2"
              >
                <Lucide name="puzzle" size={15} color="var(--ink-1)" />
                <div className="min-w-0 flex-1 leading-tight">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="text-13 font-medium text-ink-0">{e.name ?? e.id}</span>
                    {e.author && <span className="text-11 text-ink-2">by {e.author}</span>}
                    {(e.tags ?? []).map((t) => (
                      <Pill key={t} tone="outline">
                        {t}
                      </Pill>
                    ))}
                  </div>
                  {e.description && (
                    <div className="truncate text-11 text-ink-2">{e.description}</div>
                  )}
                </div>
                {isInstalled ? (
                  <>
                    <Btn
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() => void run(() => window.gb.plugins.update(e.id))}
                    >
                      update
                    </Btn>
                    <Btn
                      variant="danger"
                      size="sm"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            `Uninstall "${e.name ?? e.id}"? Its settings/data are kept.`,
                          )
                        ) {
                          void run(() => window.gb.plugins.uninstall(e.id));
                        }
                      }}
                    >
                      uninstall
                    </Btn>
                  </>
                ) : (
                  <Btn
                    variant="primary"
                    size="sm"
                    disabled={busy}
                    onClick={() => void run(() => window.gb.plugins.installFromRegistry(e.id))}
                  >
                    install
                  </Btn>
                )}
              </div>
            );
          })
        )}
      </Panel>
    </div>
  );
}
