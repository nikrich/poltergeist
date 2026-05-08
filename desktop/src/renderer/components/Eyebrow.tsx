interface Props {
  children: React.ReactNode;
  className?: string;
  // style?: transitional — call sites migrate in B.2.b–f and this prop is dropped in B.2.f
  style?: React.CSSProperties;
}

export function Eyebrow({ children, className = '' }: Props) {
  return (
    <div
      className={`font-mono text-10 font-medium uppercase tracking-eyebrow-loose text-ink-2 ${className}`}
    >
      {children}
    </div>
  );
}
