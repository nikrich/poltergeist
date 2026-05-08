interface Props {
  size?: number;
  color?: string;
  floating?: boolean;
}

export function Ghost({ size = 22, color = 'var(--neon)', floating = false }: Props) {
  return (
    <svg
      viewBox="0 0 100 110"
      style={{
        width: size,
        height: size * 1.1,
        flexShrink: 0,
        animation: floating ? 'gb-float 4s cubic-bezier(.4,0,.2,1) infinite' : 'none',
      }}
      aria-hidden="true"
    >
      <path
        d="M 50 6 C 24 6, 10 24, 10 50 L 10 94 Q 17 102, 24 95 Q 31 88, 38 95 Q 44 102, 50 95 Q 56 88, 62 95 Q 69 102, 76 95 Q 83 88, 90 94 L 90 50 C 90 24, 76 6, 50 6 Z"
        fill={color}
      />
      <circle cx="38" cy="48" r="3.2" fill="var(--bg-paper)" />
      <circle cx="62" cy="48" r="3.2" fill="var(--bg-paper)" />
    </svg>
  );
}
