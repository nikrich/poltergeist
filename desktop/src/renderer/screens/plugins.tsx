import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Btn } from '../components/Btn';
import { Pill } from '../components/Pill';
import { Toggle } from '../components/Toggle';
import { Lucide } from '../components/Lucide';
import { Eyebrow } from '../components/Eyebrow';
import { PluginCard } from '../components/PluginCard';
import { PluginDetail } from '../components/PluginDetail';
import { SkeletonRows } from '../components/SkeletonRows';
import { PanelEmpty } from '../components/PanelEmpty';
import { PanelError } from '../components/PanelError';
import { toast } from '../stores/toast';
import type { ActivePluginInfo, MarketplaceListing, PluginRecord } from '../../shared/plugin-types';

// Plugins screen: install (folder / git), enable/disable, uninstall, reload.
// Plugins are trusted code — the copy below says so at the point of install.

/** Live active-plugin list shared by Sidebar and App. */
export function useActivePlugins(): ActivePluginInfo[] {
  const [active, setActive] = useState<ActivePluginInfo[]>([]);
  useEffect(() => {
    let alive = true;
    void window.gb.plugins.active().then((a) => alive && setActive(a));
    const off = window.gb.plugins.onChanged((a) => setActive(a));
    return () => {
      alive = false;
      off();
    };
  }, []);
  return active;
}

const stateTone: Record<PluginRecord['state'], 'moss' | 'fog' | 'oxblood'> = {
  enabled: 'moss',
  disabled: 'fog',
  errored: 'oxblood',
  invalid: 'oxblood',
};

type Tab = 'installed' | 'discover';

/** At least one of record/listing is set — the other is filled in by cross-referencing id. */
interface DetailTarget {
  record: PluginRecord | null;
  listing: MarketplaceListing | null;
}

const GRID = 'grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3';

const TRUST_NOTICE = 'plugins run with full access to your machine. install only code you trust.';

export function PluginsScreen() {
  const [records, setRecords] = useState<PluginRecord[] | null>(null);
  const [gitUrl, setGitUrl] = useState('');
  const [gitSubdir, setGitSubdir] = useState('');
  const [busy, setBusy] = useState(false);
  const [listings, setListings] = useState<MarketplaceListing[] | null>(null);
  const [marketplaceError, setMarketplaceError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [activeTab, setActiveTab] = useState<Tab>('installed');
  const [detail, setDetail] = useState<DetailTarget | null>(null);
  const installedRef = useRef<HTMLElement | null>(null);
  const discoverRef = useRef<HTMLElement | null>(null);

  const refresh = useCallback(async () => {
    setRecords(await window.gb.plugins.list());
  }, []);

  const refreshMarketplace = useCallback(async () => {
    const res = await window.gb.plugins.marketplace.list();
    if (Array.isArray(res)) {
      setListings(res);
      setMarketplaceError(null);
    } else {
      setMarketplaceError(res.error);
      setListings([]);
    }
  }, []);

  useEffect(() => {
    void refresh();
    void refreshMarketplace();
  }, [refresh, refreshMarketplace]);

  const run = useCallback(
    async (action: () => Promise<{ ok: true } | { ok: false; error: string }>) => {
      setBusy(true);
      try {
        const res = await action();
        if (!res.ok && res.error !== 'cancelled') toast.error(res.error);
        await refresh();
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  const runMarketplace = useCallback(
    async (action: () => Promise<{ ok: true } | { ok: false; error: string }>) => {
      setBusy(true);
      try {
        const res = await action();
        if (!res.ok && res.error !== 'cancelled') toast.error(res.error);
        await refresh();
        await refreshMarketplace();
      } finally {
        setBusy(false);
      }
    },
    [refresh, refreshMarketplace],
  );

  const openInstalledDetail = useCallback(
    (r: PluginRecord) => setDetail({ record: r, listing: listings?.find((l) => l.id === r.id) ?? null }),
    [listings],
  );

  const openDiscoverDetail = useCallback(
    (l: MarketplaceListing) => setDetail({ record: records?.find((r) => r.id === l.id) ?? null, listing: l }),
    [records],
  );

  const filteredListings = useMemo(() => {
    if (!listings) return listings;
    const q = search.trim().toLowerCase();
    if (!q) return listings;
    return listings.filter(
      (l) =>
        l.name.toLowerCase().includes(q) ||
        l.description?.toLowerCase().includes(q) ||
        l.tags?.some((t) => t.toLowerCase().includes(q)),
    );
  }, [listings, search]);

  const scrollTo = (tab: Tab) => {
    setActiveTab(tab);
    const el = tab === 'installed' ? installedRef.current : discoverRef.current;
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-5">
      <div className="flex items-center gap-[6px]">
        <TabButton active={activeTab === 'installed'} onClick={() => scrollTo('installed')}>
          installed{records ? ` · ${records.length}` : ''}
        </TabButton>
        <TabButton active={activeTab === 'discover'} onClick={() => scrollTo('discover')}>
          discover{listings ? ` · ${listings.length}` : ''}
        </TabButton>
      </div>

      <section
        ref={installedRef}
        data-testid="installed-section"
        className="flex flex-col gap-3 rounded-r10 border border-hairline bg-vellum p-4"
      >
        <div className="flex items-center justify-between">
          <Eyebrow>installed</Eyebrow>
          <Btn variant="ghost" size="sm" disabled={busy} onClick={() => void run(() => window.gb.plugins.reload())}>
            reload
          </Btn>
        </div>

        {records === null ? (
          <div data-testid="installed-skeleton">
            <SkeletonRows count={3} />
          </div>
        ) : records.length === 0 ? (
          <PanelEmpty icon="ghost" message="nothing haunting this app yet — install a plugin below." />
        ) : (
          <div data-testid="installed-grid" className={GRID}>
            {records.map((r) => (
              <PluginCard
                key={r.id}
                icon={r.manifest?.icon}
                name={r.manifest?.name ?? r.id}
                version={r.manifest?.version}
                description={r.manifest?.description}
                error={r.error}
                meta={<Pill tone={stateTone[r.state]}>{r.state}</Pill>}
                onSelect={() => openInstalledDetail(r)}
                action={
                  <>
                    {r.manifest && (
                      <Toggle
                        on={r.state === 'enabled'}
                        disabled={busy}
                        onChange={(next) => void run(() => window.gb.plugins.setEnabled(r.id, next))}
                      />
                    )}
                    <Btn
                      variant="danger"
                      size="sm"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            `Uninstall "${r.manifest?.name ?? r.id}"? Its settings/data are kept.`,
                          )
                        ) {
                          void run(() => window.gb.plugins.uninstall(r.id));
                        }
                      }}
                    >
                      uninstall
                    </Btn>
                  </>
                }
              />
            ))}
          </div>
        )}

        <div className="flex flex-col gap-2 rounded-r6 border border-dashed border-hairline-2 p-3">
          <Eyebrow>install</Eyebrow>
          <p className="m-0 text-11 text-ink-2">{TRUST_NOTICE}</p>
          <div className="flex items-center gap-2">
            <Btn
              variant="secondary"
              size="sm"
              disabled={busy}
              icon={<Lucide name="folder-open" size={13} color="var(--ink-1)" />}
              onClick={() => void run(() => window.gb.plugins.installFromFolder())}
            >
              install from folder
            </Btn>
          </div>
          <div className="flex items-center gap-2">
            <input
              className="flex-1 rounded-r6 border border-hairline-2 bg-paper px-2 py-[6px] text-12 text-ink-0 outline-none placeholder:text-ink-2"
              placeholder="https://github.com/you/plugin-repo"
              value={gitUrl}
              onChange={(e) => setGitUrl(e.target.value)}
            />
            <input
              className="w-[180px] rounded-r6 border border-hairline-2 bg-paper px-2 py-[6px] text-12 text-ink-0 outline-none placeholder:text-ink-2"
              placeholder="subdirectory (optional)"
              value={gitSubdir}
              onChange={(e) => setGitSubdir(e.target.value)}
            />
            <Btn
              variant="secondary"
              size="sm"
              disabled={busy || !gitUrl}
              onClick={() =>
                void run(() => window.gb.plugins.installFromGit(gitUrl, gitSubdir || undefined))
              }
            >
              install from git
            </Btn>
          </div>
        </div>
      </section>

      <section
        ref={discoverRef}
        data-testid="discover-section"
        className="flex flex-col gap-3 rounded-r10 border border-hairline bg-vellum p-4"
      >
        <div className="flex items-center justify-between">
          <Eyebrow>discover</Eyebrow>
        </div>
        <p className="m-0 text-11 text-ink-2">{TRUST_NOTICE}</p>
        <input
          className="w-full rounded-r6 border border-hairline-2 bg-paper px-2 py-[6px] text-12 text-ink-0 outline-none placeholder:text-ink-2"
          placeholder="search plugins"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {listings === null ? (
          <div data-testid="discover-skeleton">
            <SkeletonRows count={4} />
          </div>
        ) : marketplaceError ? (
          <PanelError message={marketplaceError} onRetry={() => void refreshMarketplace()} />
        ) : filteredListings && filteredListings.length === 0 ? (
          listings.length === 0 ? (
            <PanelEmpty icon="store" message="no plugins in the marketplace yet." />
          ) : (
            <div className="p-3 text-12 text-ink-2">no matches.</div>
          )
        ) : (
          <div data-testid="discover-grid" className={GRID}>
            {filteredListings?.map((l) => (
              <PluginCard
                key={l.id}
                icon={l.icon}
                name={l.name}
                version={l.version}
                author={l.author}
                description={l.description}
                meta={l.updateAvailable && <Pill tone="neon">update available</Pill>}
                onSelect={() => openDiscoverDetail(l)}
                action={
                  !l.installed ? (
                    <Btn
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() => void runMarketplace(() => window.gb.plugins.marketplace.install(l.id))}
                    >
                      install
                    </Btn>
                  ) : l.updateAvailable ? (
                    <Btn
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() => void runMarketplace(() => window.gb.plugins.marketplace.update(l.id))}
                    >
                      update
                    </Btn>
                  ) : (
                    <Pill tone="fog">installed</Pill>
                  )
                }
              />
            ))}
          </div>
        )}
      </section>

      {detail &&
        (() => {
          const { record, listing } = detail;
          const id = listing?.id ?? record?.id ?? '';
          const installed = !!record || !!listing?.installed;
          const updateAvailable = listing?.updateAvailable ?? false;
          return (
            <PluginDetail
              name={listing?.name ?? record?.manifest?.name ?? record?.id ?? ''}
              icon={listing?.icon ?? record?.manifest?.icon}
              version={listing?.version ?? record?.manifest?.version}
              author={listing?.author}
              description={listing?.description ?? record?.manifest?.description}
              tags={listing?.tags}
              repo={listing?.repo}
              installed={installed}
              installedVersion={listing?.installedVersion ?? record?.manifest?.version ?? null}
              updateAvailable={updateAvailable}
              enabled={record?.state === 'enabled'}
              busy={busy}
              onClose={() => setDetail(null)}
              onInstall={
                listing && !installed
                  ? () => void runMarketplace(() => window.gb.plugins.marketplace.install(id))
                  : undefined
              }
              onUpdate={
                listing && installed && updateAvailable
                  ? () => void runMarketplace(() => window.gb.plugins.marketplace.update(id))
                  : undefined
              }
              onToggleEnabled={
                record?.manifest
                  ? (next) => void run(() => window.gb.plugins.setEnabled(id, next))
                  : undefined
              }
              onUninstall={
                record
                  ? () => {
                      if (
                        window.confirm(
                          `Uninstall "${record.manifest?.name ?? record.id}"? Its settings/data are kept.`,
                        )
                      ) {
                        void run(() => window.gb.plugins.uninstall(id));
                      }
                    }
                  : undefined
              }
            />
          );
        })()}
    </div>
  );
}

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function TabButton({ active, onClick, children }: TabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`cursor-pointer rounded-sm border px-[10px] py-1 font-mono text-11 lowercase ${
        active
          ? 'border-neon/30 bg-neon/15 text-neon-ink'
          : 'border-hairline-2 bg-transparent text-ink-1'
      }`}
    >
      {children}
    </button>
  );
}
