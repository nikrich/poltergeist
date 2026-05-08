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
    <label
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        fontSize: 12,
        color: 'var(--ink-1)',
        cursor: 'pointer',
      }}
    >
      <button
        type="button"
        onClick={toggle}
        style={{
          width: 28,
          height: 16,
          borderRadius: 999,
          background: on ? 'var(--neon)' : 'var(--bg-fog)',
          border: '1px solid var(--hairline-2)',
          position: 'relative',
          cursor: 'pointer',
          flexShrink: 0,
          transition: 'background 120ms',
        }}
      >
        <span
          style={{
            position: 'absolute',
            top: 1,
            left: on ? 13 : 1,
            width: 12,
            height: 12,
            borderRadius: '50%',
            background: on ? '#0E0F12' : 'var(--ink-2)',
            transition: 'left 160ms cubic-bezier(.2,.8,.2,1)',
          }}
        />
      </button>
      {label && <span>{label}</span>}
    </label>
  );
}
