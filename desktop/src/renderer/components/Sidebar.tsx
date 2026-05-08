import { useState } from 'react';
import { Lucide } from './Lucide';
import { Ghost } from './Ghost';
import { Eyebrow } from './Eyebrow';
import { useNavigation, type ScreenId } from '../stores/navigation';
import { useMeeting } from '../stores/meeting';
import { isMac } from '../lib/platform';

const NAV_ITEMS: Array<{ id: ScreenId; icon: string; label: string }> = [
  { id: 'today', icon: 'sparkles', label: 'today' },
  { id: 'connectors', icon: 'plug', label: 'connectors' },
  { id: 'meetings', icon: 'mic', label: 'meetings' },
  { id: 'capture', icon: 'inbox', label: 'capture' },
  { id: 'vault', icon: 'book-open', label: 'vault' },
  { id: 'settings', icon: 'settings', label: 'settings' },
];

const VAULT_FOLDERS = [
  { icon: 'folder', label: 'Daily', count: 284 },
  { icon: 'folder', label: 'Meetings', count: 47 },
  { icon: 'folder', label: 'People', count: 91 },
  { icon: 'folder', label: 'Projects', count: 23 },
  { icon: 'hash', label: '#followup', count: 8 },
];

function RecordingDot() {
  return (
    <span
      style={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: 'var(--oxblood)',
        boxShadow: '0 0 0 0 rgba(255,107,90,0.6)',
        animation: 'gb-pulse 1.4s ease-out infinite',
      }}
    />
  );
}

export function Sidebar() {
  const { active, setActive } = useNavigation();
  const phase = useMeeting((s) => s.phase);
  return (
    <aside
      style={
        {
          width: 220,
          flexShrink: 0,
          background: 'var(--bg-paper)',
          borderRight: '1px solid var(--hairline)',
          display: 'flex',
          flexDirection: 'column',
          WebkitAppRegion: 'drag',
        } as React.CSSProperties
      }
    >
      {isMac && <div style={{ height: 36, flexShrink: 0 }} />}

      <div style={{ padding: '14px 14px 8px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <Ghost size={20} floating />
        <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
          <span
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 16,
              fontWeight: 600,
              color: 'var(--ink-0)',
              letterSpacing: '-0.02em',
            }}
          >
            ghostbrain
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              color: 'var(--ink-2)',
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
            }}
          >
            v 0.1.0 · haunting
          </span>
        </div>
      </div>

      <nav
        style={
          {
            padding: '12px 8px',
            flex: 1,
            overflowY: 'auto',
            WebkitAppRegion: 'no-drag',
          } as React.CSSProperties
        }
      >
        <Eyebrow style={{ padding: '6px 10px' }}>workspace</Eyebrow>
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
        <Eyebrow style={{ padding: '6px 10px', marginTop: 16 }}>vault</Eyebrow>
        {VAULT_FOLDERS.map((f) => (
          <VaultRow key={f.label} {...f} />
        ))}
      </nav>

      <div
        style={
          {
            padding: '10px 14px',
            borderTop: '1px solid var(--hairline)',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            WebkitAppRegion: 'no-drag',
          } as React.CSSProperties
        }
      >
        <div
          style={{
            width: 26,
            height: 26,
            borderRadius: 4,
            background: 'var(--bg-fog)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <Lucide name="hard-drive" size={13} color="var(--ink-1)" />
        </div>
        <div style={{ flex: 1, minWidth: 0, lineHeight: 1.2 }}>
          <div
            style={{
              fontSize: 11,
              color: 'var(--ink-0)',
              fontWeight: 500,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            ~/ghostbrain/vault
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--ink-2)' }}>
            local · synced
          </div>
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
  const [hover, setHover] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '7px 10px',
        borderRadius: 6,
        cursor: 'pointer',
        background: active ? 'rgba(197,255,61,0.12)' : hover ? 'var(--bg-vellum)' : 'transparent',
        color: active ? 'var(--ink-0)' : 'var(--ink-1)',
        fontSize: 13,
        fontWeight: active ? 500 : 400,
        position: 'relative',
        transition: 'background 120ms',
      }}
    >
      {active && (
        <div
          style={{
            position: 'absolute',
            left: -8,
            top: 6,
            bottom: 6,
            width: 2,
            background: 'var(--neon)',
            borderRadius: 2,
          }}
        />
      )}
      <Lucide name={item.icon} size={15} color={active ? 'var(--neon)' : 'var(--ink-2)'} />
      <span style={{ flex: 1 }}>{item.label}</span>
      {badge &&
        (typeof badge === 'string' ? (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ink-2)' }}>
            {badge}
          </span>
        ) : (
          badge
        ))}
    </div>
  );
}

function VaultRow({ icon, label, count }: { icon: string; label: string; count: number }) {
  const [hover, setHover] = useState(false);
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '5px 10px',
        borderRadius: 4,
        cursor: 'pointer',
        background: hover ? 'var(--bg-vellum)' : 'transparent',
        fontSize: 12,
        color: 'var(--ink-1)',
      }}
    >
      <Lucide name={icon} size={12} color="var(--ink-3)" />
      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {label}
      </span>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--ink-3)' }}>
        {count}
      </span>
    </div>
  );
}
