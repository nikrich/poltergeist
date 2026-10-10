import { BrainConstellation } from '../components/BrainConstellation';
import { LinkGraph } from '../components/LinkGraph';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { useGraphView, type VaultTab } from '../stores/graph-view';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';

const TABS: VaultTab[] = ['constellation', 'graph'];

export function VaultScreen() {
  const vaultPath = useSettings((s) => s.vaultPath);
  const tab = useGraphView((s) => s.tab);
  const setTab = useGraphView((s) => s.setTab);
  const onOpen = async () => {
    const result = await window.gb.shell.openPath(vaultPath);
    if (!result.ok) toast.error(result.error);
  };
  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar
        title="vault"
        subtitle={tab === 'graph' ? 'links around one page' : 'opens in your file manager'}
        right={
          <div className="flex items-center gap-3">
            <div role="tablist" aria-label="vault views" className="flex rounded-pill border border-hairline p-[2px]">
              {TABS.map((t) => (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={tab === t}
                  onClick={() => setTab(t)}
                  className={`rounded-pill px-3 py-[4px] font-mono text-11 ${
                    tab === t ? 'bg-vellum text-ink-0' : 'text-ink-2 hover:text-ink-0'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="external-link" size={13} />}
              onClick={onOpen}
            >
              open vault folder
            </Btn>
          </div>
        }
      />
      {tab === 'constellation' ? <BrainConstellation /> : <LinkGraph />}
    </div>
  );
}
