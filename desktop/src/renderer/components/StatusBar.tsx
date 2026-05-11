import { Lucide } from './Lucide';
import { useMeeting } from '../stores/meeting';

export function StatusBar() {
  const { phase } = useMeeting();
  return (
    <footer className="gb-statusbar flex h-[26px] flex-shrink-0 items-center gap-4 border-t border-hairline bg-vellum px-[14px] font-mono text-10 lowercase text-ink-2">
      <span className="inline-flex items-center gap-[5px]">
        <span className="h-[6px] w-[6px] rounded-full bg-neon" />
        6 connectors live
      </span>
      <span>·</span>
      <span>2,489 indexed</span>
      <span>·</span>
      <span>last sync 1m ago</span>
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
        <Lucide name="cpu" size={9} /> 0.4% cpu
      </span>
      <span>·</span>
      <span>vault encrypted</span>
    </footer>
  );
}
