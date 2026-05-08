type Tone = 'neon' | 'moss' | 'oxblood' | 'fog' | 'outline';

interface Props {
  tone?: Tone;
  children: React.ReactNode;
  style?: React.CSSProperties;
}

const palettes: Record<Tone, { bg: string; fg: string; border?: string }> = {
  neon: { bg: 'rgba(197,255,61,0.15)', fg: 'var(--neon)' },
  moss: { bg: 'rgba(92,124,79,0.18)', fg: '#A2C795' },
  oxblood: { bg: 'rgba(255,107,90,0.14)', fg: '#FF8A7C' },
  fog: { bg: 'var(--bg-fog)', fg: 'var(--ink-1)' },
  outline: { bg: 'transparent', fg: 'var(--ink-2)', border: '1px solid var(--hairline-2)' },
};

export function Pill({ tone = 'neon', children, style }: Props) {
  const p = palettes[tone];
  return (
    <span
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        fontWeight: 500,
        padding: '2px 7px',
        borderRadius: 4,
        background: p.bg,
        color: p.fg,
        border: p.border ?? 'none',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        textTransform: 'lowercase',
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {children}
    </span>
  );
}
