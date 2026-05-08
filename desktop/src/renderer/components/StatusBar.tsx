import { Lucide } from './Lucide';
import { useMeeting } from '../stores/meeting';

export function StatusBar() {
  const phase = useMeeting((s) => s.phase);
  return (
    <footer
      style={{
        height: 26,
        flexShrink: 0,
        borderTop: '1px solid var(--hairline)',
        background: 'var(--bg-vellum)',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '0 14px',
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        color: 'var(--ink-2)',
        textTransform: 'lowercase',
      }}
    >
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--neon)' }} />6
        connectors live
      </span>
      <span>·</span>
      <span>2,489 indexed</span>
      <span>·</span>
      <span>last sync 1m ago</span>
      {phase === 'recording' && (
        <>
          <span>·</span>
          <span
            style={{
              color: 'var(--oxblood)',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: 'var(--oxblood)',
                animation: 'gb-pulse 1.4s ease-out infinite',
              }}
            />
            recording
          </span>
        </>
      )}
      <div style={{ flex: 1 }} />
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        <Lucide name="cpu" size={9} /> 0.4% cpu
      </span>
      <span>·</span>
      <span>vault encrypted</span>
    </footer>
  );
}
