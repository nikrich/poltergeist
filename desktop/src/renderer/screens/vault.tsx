import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Ghost } from '../components/Ghost';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';

export function VaultScreen() {
  const vaultPath = useSettings((s) => s.vaultPath);
  const onOpen = async () => {
    const result = await window.gb.shell.openPath(vaultPath);
    if (!result.ok) toast.error(result.error);
  };
  return (
    <div className="flex flex-1 flex-col bg-paper">
      <TopBar title="vault" subtitle="opens in your file manager" />
      <div className="flex flex-1 flex-col items-center justify-center gap-[18px] p-12">
        <Ghost size={72} floating />
        <h2 className="m-0 font-display text-28 font-semibold tracking-tight-x text-ink-0">
          your vault is on disk.
        </h2>
        <p className="m-0 max-w-[380px] text-center text-14 text-ink-2">
          poltergeist doesn&rsquo;t replace your editor — it feeds the vault. open it to see
          everything as markdown.
        </p>
        <Btn
          variant="primary"
          size="lg"
          // intentional fixed color: icon must read dark on the always-bright neon button
          icon={<Lucide name="external-link" size={14} color="#0E0F12" />}
          onClick={onOpen}
        >
          open vault folder
        </Btn>
        <span className="font-mono text-11 text-ink-3">{vaultPath}</span>
      </div>
    </div>
  );
}
