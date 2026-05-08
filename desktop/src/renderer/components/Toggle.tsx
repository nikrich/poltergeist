interface Props {
  label?: string;
  on: boolean;
  onChange?: (next: boolean) => void;
  disabled?: boolean;
}

export function Toggle({ label, on, onChange, disabled }: Props) {
  return (
    <label
      className={`flex items-center gap-[10px] text-12 text-ink-1 ${disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}
    >
      <button
        type="button"
        onClick={() => !disabled && onChange?.(!on)}
        disabled={disabled}
        aria-pressed={on}
        className={`relative h-4 w-7 flex-shrink-0 rounded-pill border border-hairline-2 transition-colors duration-[120ms] ${on ? 'bg-neon' : 'bg-fog'} ${disabled ? '' : 'cursor-pointer'}`}
      >
        <span
          className={`absolute top-px h-3 w-3 rounded-full transition-[left] duration-[160ms] ease-[cubic-bezier(.2,.8,.2,1)] ${on ? 'left-[13px] bg-paper' : 'left-px bg-ink-2'}`}
        />
      </button>
      {label && <span>{label}</span>}
    </label>
  );
}
