import { Lucide } from './Lucide';
import { useMeeting } from '../stores/meeting';
import { useConnectors, useVaultStats } from '../lib/api/hooks';

function relativeMinutes(iso: string | null | undefined): string {
  if (!iso) return 'never';
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return 'unknown';
  const seconds = Math.floor((Date.now() - ms) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

export function StatusBar() {
  const { phase } = useMeeting();
  const connectors = useConnectors();
  const stats = useVaultStats();
  const liveConnectors =
    connectors.data?.filter((c) => c.state === 'on').length ?? 0;
  const indexedCount = stats.data?.indexedCount ?? null;
  const lastSyncLabel = relativeMinutes(stats.data?.lastSyncAt ?? null);
  return (
    <footer className="gb-statusbar flex h-[26px] flex-shrink-0 items-center gap-4 border-t border-hairline bg-vellum px-[14px] font-mono text-10 lowercase text-ink-2">
      <span className="inline-flex items-center gap-[5px]">
        <span
          className={`h-[6px] w-[6px] rounded-full ${
            liveConnectors > 0 ? 'bg-neon' : 'bg-ink-3'
          }`}
        />
        {connectors.data
          ? `${liveConnectors} connector${liveConnectors === 1 ? '' : 's'} live`
          : '…'}
      </span>
      <span>·</span>
      <span>{indexedCount !== null ? `${indexedCount.toLocaleString()} indexed` : '…'}</span>
      <span>·</span>
      <span>last sync {lastSyncLabel}</span>
      {phase === 'recording' && (
        <>
          <span>·</span>
          <span className="inline-flex items-center gap-[5px] text-oxblood">
            <span
              className="h-[6px] w-[6px] rounded-full bg-oxblood"
              style={{ animation: 'gb-pulse 1.4s ease-out infinite' }}
            />
            recording
          </span>
        </>
      )}
      <div className="flex-1" />
      <span className="inline-flex items-center gap-[5px]">
        <Lucide name="cpu" size={9} /> ghost-brain
      </span>
      <span>·</span>
      <span>vault encrypted</span>
    </footer>
  );
}
