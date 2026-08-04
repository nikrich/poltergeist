import { BrainConstellation } from '../components/BrainConstellation';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';

export function VaultScreen() {
  const vaultPath = useSettings((s) => s.vaultPath);
  const onOpen = async () => {
    const result = await window.gb.shell.openPath(vaultPath);
    if (!result.ok) toast.error(result.error);
  };
  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar
        title="vault"
        subtitle="opens in your file manager"
        right={
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="external-link" size={13} />}
            onClick={onOpen}
          >
            open vault folder
          </Btn>
        }
      />
      <BrainConstellation />
    </div>
  );
}
