import { Lucide } from './Lucide';

interface Props {
  icon?: string;
  name: string;
  version?: string;
  author?: string;
  description?: string;
  /** Rendered inline after the version (state/update pills etc). */
  meta?: React.ReactNode;
  /** Primary action slot — a button, pill, or a group of controls. */
  action?: React.ReactNode;
  error?: string;
}

export function PluginCard({ icon, name, version, author, description, meta, action, error }: Props) {
  return (
    <div className="flex flex-col gap-2 rounded-r10 border border-hairline bg-vellum p-3">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-r6 border border-hairline bg-paper">
          <Lucide name={icon ?? 'puzzle'} size={16} color="var(--ink-1)" />
        </div>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="text-13 font-medium text-ink-0">{name}</span>
            {version && <span className="font-mono text-10 text-ink-2">{version}</span>}
            {meta}
          </div>
          {author && <div className="truncate text-10 text-ink-2">{author}</div>}
        </div>
      </div>
      {description && <p className="m-0 text-11 leading-[1.4] text-ink-2">{description}</p>}
      {error && <div className="text-11 text-oxblood">{error}</div>}
      {action && <div className="mt-1 flex items-center justify-between gap-2">{action}</div>}
    </div>
  );
}
