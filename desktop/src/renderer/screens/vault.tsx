import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Ghost } from '../components/Ghost';
import { useSettings } from '../stores/settings';

export function VaultScreen() {
  const vaultPath = useSettings((s) => s.vaultPath);
  const onOpen = () => {
    window.gb.shell.openPath(vaultPath);
  };
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: 'var(--bg-paper)' }}>
      <TopBar title="vault" subtitle="opens in your file manager" />
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 18,
          padding: 48,
        }}
      >
        <Ghost size={72} floating />
        <h2
          style={{
            margin: 0,
            fontFamily: 'var(--font-display)',
            fontSize: 28,
            fontWeight: 600,
            letterSpacing: '-0.025em',
            color: 'var(--ink-0)',
          }}
        >
          your vault is on disk.
        </h2>
        <p
          style={{
            margin: 0,
            fontSize: 14,
            color: 'var(--ink-2)',
            textAlign: 'center',
            maxWidth: 380,
          }}
        >
          ghostbrain doesn't replace your editor — it feeds the vault. open it to see everything as markdown.
        </p>
        <Btn
          variant="primary"
          size="lg"
          icon={<Lucide name="external-link" size={14} color="#0E0F12" />}
          onClick={onOpen}
        >
          open vault folder
        </Btn>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-3)' }}>
          {vaultPath}
        </span>
      </div>
    </div>
  );
}
