export type BoardMode = 'stickies' | 'architecture';

interface Props {
  mode: BoardMode;
  onChange: (mode: BoardMode) => void;
  className?: string;
}

/** Stickies ↔ Architecture switch for an event-storming board. */
export function BoardModeToggle({ mode, onChange, className = '' }: Props) {
  return (
    <div className={`flex items-center gap-[2px] ${className}`}>
      {(['stickies', 'architecture'] as const).map((m) => (
        <button
          key={m}
          type="button"
          aria-pressed={mode === m}
          onClick={() => onChange(m)}
          className={`cursor-pointer rounded-sm px-2 py-[2px] font-mono text-11 ${
            mode === m ? 'bg-neon/15 text-neon-ink' : 'text-ink-2 hover:text-ink-0'
          }`}
        >
          {m === 'stickies' ? 'Stickies' : 'Architecture'}
        </button>
      ))}
    </div>
  );
}
