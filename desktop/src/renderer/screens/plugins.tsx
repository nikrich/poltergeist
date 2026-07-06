import { useCallback, useEffect, useState } from 'react';
import { Panel } from '../components/Panel';
import { Btn } from '../components/Btn';
import { Pill } from '../components/Pill';
import { Toggle } from '../components/Toggle';
import { Lucide } from '../components/Lucide';
import { toast } from '../stores/toast';
import type { ActivePluginInfo, PluginRecord } from '../../shared/plugin-types';

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

export function PluginsScreen() {
  const [records, setRecords] = useState<PluginRecord[] | null>(null);
  const [gitUrl, setGitUrl] = useState('');
  const [gitSubdir, setGitSubdir] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setRecords(await window.gb.plugins.list());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-5">
      <Panel
        title="installed plugins"
        subtitle={records ? `${records.length}` : undefined}
        action={
          <Btn variant="ghost" size="sm" disabled={busy} onClick={() => void run(() => window.gb.plugins.reload())}>
            reload
          </Btn>
        }
      >
        {records === null ? (
          <div className="p-3 text-12 text-ink-2">…</div>
        ) : records.length === 0 ? (
          <div className="p-3 text-12 text-ink-2">
            nothing haunting this app yet — install a plugin below.
          </div>
        ) : (
          records.map((r) => (
            <div
              key={r.id}
              className="flex items-center gap-3 rounded-r6 border border-hairline bg-paper px-3 py-2"
            >
              <Lucide name={r.manifest?.icon ?? 'puzzle'} size={15} color="var(--ink-1)" />
              <div className="min-w-0 flex-1 leading-tight">
                <div className="flex items-baseline gap-2">
                  <span className="text-13 font-medium text-ink-0">
                    {r.manifest?.name ?? r.id}
                  </span>
                  <span className="font-mono text-10 text-ink-2">
                    {r.manifest?.version ?? '—'}
                  </span>
                  <Pill tone={stateTone[r.state]}>{r.state}</Pill>
                </div>
                {r.manifest?.description && (
                  <div className="truncate text-11 text-ink-2">{r.manifest.description}</div>
                )}
                {r.error && <div className="text-11 text-oxblood">{r.error}</div>}
              </div>
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
            </div>
          ))
        )}
      </Panel>

      <Panel title="install" subtitle="trusted code only">
        <p className="m-0 px-1 text-11 text-ink-2">
          plugins run with full access to your machine. install only code you trust.
        </p>
        <div className="flex items-center gap-2 px-1 py-2">
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
        <div className="flex items-center gap-2 px-1">
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
      </Panel>
    </div>
  );
}
