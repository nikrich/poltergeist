import { useState } from 'react';

interface Props {
  label?: string;
  on: boolean;
  onChange?: (next: boolean) => void;
}

export function Toggle({ label, on: initial, onChange }: Props) {
  const [on, setOn] = useState(initial);
  const toggle = () => {
    const next = !on;
    setOn(next);
    onChange?.(next);
  };
  return (
    <label className="flex cursor-pointer items-center gap-[10px] text-12 text-ink-1">
      <button
        type="button"
        onClick={toggle}
        aria-pressed={on}
        className={`relative h-4 w-7 flex-shrink-0 cursor-pointer rounded-pill border border-hairline-2 transition-colors duration-[120ms] ${on ? 'bg-neon' : 'bg-fog'}`}
      >
        <span
          className={`absolute top-px h-3 w-3 rounded-full transition-[left] duration-[160ms] ease-[cubic-bezier(.2,.8,.2,1)] ${on ? 'left-[13px] bg-paper' : 'left-px bg-ink-2'}`}
        />
      </button>
      {label && <span>{label}</span>}
    </label>
  );
}
