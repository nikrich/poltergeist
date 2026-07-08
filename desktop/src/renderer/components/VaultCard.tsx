import { Btn } from './Btn';
import { Lucide } from './Lucide';
import { Pill } from './Pill';
import { toast } from '../stores/toast';

// Used by the G2 onboarding wizard's vault step to display/config the vault
// path — this used to live in the retired setup.tsx recipe screen.
export function VaultCard({ vaultPath }: { vaultPath: string }) {
  const onOpen = async () => {
    if (!vaultPath) return;
    const result = await window.gb.shell.openPath(vaultPath);
    if (!result.ok) toast.error(result.error);
  };
  return (
    <div className="rounded-lg border border-hairline bg-vellum p-4">
      <div className="flex items-center gap-3">
        <Lucide name="folder-open" size={14} color="var(--ink-2)" />
        <div className="min-w-0 flex-1 leading-[1.25]">
          <div className="text-13 font-medium text-ink-0">vault path</div>
          <div className="truncate font-mono text-11 text-ink-2">
            {vaultPath || '(not configured)'}
          </div>
        </div>
        <Pill tone={vaultPath ? 'moss' : 'fog'}>
          {vaultPath ? 'configured' : 'set in settings'}
        </Pill>
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="external-link" size={12} />}
          onClick={onOpen}
          disabled={!vaultPath}
        >
          open
        </Btn>
      </div>
      <p className="mt-3 max-w-[60ch] text-12 leading-[1.55] text-ink-2">
        the vault is where everything poltergeist captures gets written. open it
        in Obsidian for the best experience — install the Dataview, Templater,
        Periodic Notes, and Local REST API plugins from the in-app community
        marketplace.
      </p>
    </div>
  );
}
