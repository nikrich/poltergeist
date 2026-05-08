interface Props {
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export function Eyebrow({ children, style }: Props) {
  return (
    <div
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        fontWeight: 500,
        textTransform: 'uppercase',
        letterSpacing: '0.14em',
        color: 'var(--ink-2)',
        ...style,
      }}
    >
      {children}
    </div>
  );
}
