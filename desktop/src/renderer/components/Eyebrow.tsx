interface Props {
  children: React.ReactNode;
  className?: string;
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
