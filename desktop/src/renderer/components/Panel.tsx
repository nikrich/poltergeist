interface Props {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export function Panel({ title, subtitle, action, children, style }: Props) {
  return (
    <section
      style={{
        background: 'var(--bg-vellum)',
        border: '1px solid var(--hairline)',
        borderRadius: 10,
        ...style,
      }}
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '12px 16px',
          borderBottom: '1px solid var(--hairline)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flex: 1 }}>
          <h3 style={{ margin: 0, fontSize: 13, fontWeight: 500, color: 'var(--ink-0)' }}>
            {title}
          </h3>
          {subtitle && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ink-2)' }}>
              {subtitle}
            </span>
          )}
        </div>
        {action}
      </header>
      <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 4 }}>
        {children}
      </div>
    </section>
  );
}
