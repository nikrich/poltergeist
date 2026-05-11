import { Lucide } from './Lucide';
import { Ghost } from './Ghost';
import { Eyebrow } from './Eyebrow';
import { useNavigation, type ScreenId } from '../stores/navigation';
import { useMeeting } from '../stores/meeting';
import { useDaily, useMeetings } from '../lib/api/hooks';
import { isMac } from '../lib/platform';

const NAV_ITEMS: Array<{ id: ScreenId; icon: string; label: string }> = [
  { id: 'today', icon: 'sparkles', label: 'today' },
  { id: 'connectors', icon: 'plug', label: 'connectors' },
  { id: 'meetings', icon: 'mic', label: 'meetings' },
  { id: 'capture', icon: 'inbox', label: 'capture' },
  { id: 'vault', icon: 'book-open', label: 'vault' },
  { id: 'settings', icon: 'settings', label: 'settings' },
];

function RecordingDot() {
  return (
    <span
      className="h-2 w-2 rounded-full bg-oxblood"
      style={{ animation: 'gb-pulse 1.4s ease-out infinite' }}
    />
  );
}

export function Sidebar() {
  const { active, setActive } = useNavigation();
  const phase = useMeeting((s) => s.phase);
  const daily = useDaily({ limit: 1 });
  const meetings = useMeetings({ limit: 1 });
  const vaultFolders: Array<{ id: ScreenId; icon: string; label: string; count: number | null }> = [
    { id: 'daily', icon: 'folder', label: 'Daily', count: daily.data?.total ?? null },
    { id: 'meetings', icon: 'folder', label: 'Meetings', count: meetings.data?.total ?? null },
  ];
  return (
    <aside
      className="flex w-[220px] flex-shrink-0 flex-col border-r border-hairline bg-paper"
      style={{ WebkitAppRegion: 'drag' }}
    >
      {isMac && <div className="h-9 flex-shrink-0" />}

      <div className="flex items-center gap-[10px] px-[14px] pb-2 pt-[14px]">
        <Ghost size={20} floating />
        <div className="flex flex-col leading-[1.1]">
          <span className="font-display text-16 font-semibold tracking-tight-xx text-ink-0">
            ghostbrain
          </span>
          <span className="font-mono text-9 uppercase tracking-eyebrow text-ink-2">
            v 0.1.0 · haunting
          </span>
        </div>
      </div>

      <nav
        className="gb-sidenav flex-1 overflow-y-auto px-2 py-3"
        style={{ WebkitAppRegion: 'no-drag' }}
      >
        <Eyebrow className="px-[10px] py-[6px]">workspace</Eyebrow>
        {NAV_ITEMS.map((item) => (
          <NavRow
            key={item.id}
            item={item}
            active={active === item.id}
            onClick={() => setActive(item.id)}
            badge={
              item.id === 'meetings' && phase === 'recording' ? (
                <RecordingDot />
              ) : item.id === 'capture' ? (
                '12'
              ) : null
            }
          />
        ))}
        <Eyebrow className="mt-4 px-[10px] py-[6px]">vault</Eyebrow>
        {vaultFolders.map((f) => (
          <VaultRow
            key={f.id}
            icon={f.icon}
            label={f.label}
            count={f.count}
            active={active === f.id}
            onClick={() => setActive(f.id)}
          />
        ))}
      </nav>

      <div
        className="flex items-center gap-2 border-t border-hairline px-[14px] py-[10px]"
        style={{ WebkitAppRegion: 'no-drag' }}
      >
        <div className="flex h-[26px] w-[26px] flex-shrink-0 items-center justify-center rounded-sm bg-fog">
          <Lucide name="hard-drive" size={13} color="var(--ink-1)" />
        </div>
        <div className="min-w-0 flex-1 leading-[1.2]">
          <div className="overflow-hidden text-ellipsis whitespace-nowrap text-11 font-medium text-ink-0">
            ~/ghostbrain/vault
          </div>
          <div className="font-mono text-9 text-ink-2">local · synced</div>
        </div>
      </div>
    </aside>
  );
}

function NavRow({
  item,
  active,
  onClick,
  badge,
}: {
  item: { id: ScreenId; icon: string; label: string };
  active: boolean;
  onClick: () => void;
  badge: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`gb-navrow relative flex w-full items-center gap-[10px] rounded-r6 px-[10px] py-[7px] text-left text-13 transition-colors duration-[120ms] ${
        active ? 'bg-neon/12 font-medium text-ink-0' : 'font-normal text-ink-1 hover:bg-vellum'
      }`}
    >
      {active && (
        <span className="absolute -left-2 bottom-[6px] top-[6px] w-[2px] rounded-sm bg-neon" />
      )}
      <Lucide name={item.icon} size={15} color={active ? 'var(--neon)' : 'var(--ink-2)'} />
      <span className="flex-1">{item.label}</span>
      {badge &&
        (typeof badge === 'string' ? (
          <span className="font-mono text-10 text-ink-2">{badge}</span>
        ) : (
          badge
        ))}
    </button>
  );
}

function VaultRow({
  icon,
  label,
  count,
  active,
  onClick,
}: {
  icon: string;
  label: string;
  count: number | null;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-sm px-[10px] py-[5px] text-left text-12 transition-colors duration-[120ms] ${
        active ? 'bg-neon/12 font-medium text-ink-0' : 'text-ink-1 hover:bg-vellum'
      }`}
    >
      <Lucide name={icon} size={12} color={active ? 'var(--neon)' : 'var(--ink-3)'} />
      <span className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap">{label}</span>
      <span className="font-mono text-9 text-ink-3">{count ?? '—'}</span>
    </button>
  );
}
