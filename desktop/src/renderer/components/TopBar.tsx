interface Props {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}

export function TopBar({ title, subtitle, right }: Props) {
  return (
    <div className="gb-topbar flex h-14 flex-shrink-0 items-center gap-4 border-b border-hairline bg-paper px-6">
      <div className="flex flex-col gap-[2px] leading-[1.15]">
        <h1 className="m-0 font-display text-20 font-semibold tracking-tight-xx text-ink-0">
          {title}
        </h1>
        {subtitle && (
          <span className="font-mono text-10 uppercase tracking-eyebrow text-ink-2">
            {subtitle}
          </span>
        )}
      </div>
      <div className="flex-1" />
      {right}
    </div>
  );
}
