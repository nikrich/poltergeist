interface Props {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  // style?: transitional — call sites migrate in B.2.b–f and this prop is dropped in B.2.f
  style?: React.CSSProperties;
}

export function Panel({ title, subtitle, action, children, className = '' }: Props) {
  return (
    <section className={`rounded-r10 border border-hairline bg-vellum ${className}`}>
      <header className="gb-panel-header flex items-center gap-[10px] border-b border-hairline px-4 py-3">
        <div className="flex flex-1 items-baseline gap-[10px]">
          <h3 className="m-0 text-13 font-medium text-ink-0">{title}</h3>
          {subtitle && (
            <span className="font-mono text-10 text-ink-2">{subtitle}</span>
          )}
        </div>
        {action}
      </header>
      <div className="gb-panel-body flex flex-col gap-1 p-3">{children}</div>
    </section>
  );
}
