import { Btn } from './Btn';
import { Lucide } from './Lucide';
import { Pill } from './Pill';

const TRUST_NOTICE = 'plugins run with full access to your machine. install only code you trust.';

interface Props {
  name: string;
  icon?: string;
  version?: string;
  author?: string;
  description?: string;
  tags?: string[];
  repo?: string;
  installed: boolean;
  installedVersion?: string | null;
  updateAvailable: boolean;
  enabled?: boolean;
  busy: boolean;
  onClose: () => void;
  onInstall?: () => void;
  onUpdate?: () => void;
  onToggleEnabled?: (next: boolean) => void;
  onUninstall?: () => void;
}

export function PluginDetail({
  name,
  icon,
  version,
  author,
  description,
  tags,
  repo,
  installed,
  installedVersion,
  updateAvailable,
  enabled,
  busy,
  onClose,
  onInstall,
  onUpdate,
  onToggleEnabled,
  onUninstall,
}: Props) {
  const showTrustNotice = !!(onInstall || onUpdate);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`${name} details`}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex max-h-[80vh] w-[420px] flex-col gap-3 overflow-y-auto rounded-r6 border border-hairline-2 bg-paper p-5 shadow-card">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-r6 border border-hairline bg-vellum">
              <Lucide name={icon ?? 'puzzle'} size={18} color="var(--ink-1)" />
            </div>
            <div className="leading-tight">
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="text-14 font-medium text-ink-0">{name}</span>
                {version && <span className="font-mono text-11 text-ink-2">{version}</span>}
              </div>
              {author && <div className="text-11 text-ink-2">{author}</div>}
            </div>
          </div>
          <button
            type="button"
            aria-label="close"
            onClick={onClose}
            className="rounded-sm p-[2px] text-ink-2 hover:text-ink-0"
          >
            <Lucide name="x" size={14} />
          </button>
        </div>

        {description && <p className="m-0 text-12 leading-[1.5] text-ink-1">{description}</p>}

        <div className="flex flex-col gap-1 text-11 text-ink-2">
          {installed && (
            <div className="flex items-center gap-2">
              installed version: <span className="font-mono text-ink-0">{installedVersion ?? version ?? '—'}</span>
              {updateAvailable && <Pill tone="neon">update available</Pill>}
            </div>
          )}
          {repo && (
            <div>
              source:{' '}
              <button
                type="button"
                onClick={() => void window.gb.shell.openExternal(repo)}
                className="text-neon-ink underline"
              >
                {repo}
              </button>
            </div>
          )}
        </div>

        {tags && tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {tags.map((t) => (
              <Pill key={t} tone="fog">
                {t}
              </Pill>
            ))}
          </div>
        )}

        {showTrustNotice && <p className="m-0 text-11 text-ink-2">{TRUST_NOTICE}</p>}

        <div className="mt-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {onToggleEnabled && (
              <Btn
                variant="secondary"
                size="sm"
                disabled={busy}
                onClick={() => onToggleEnabled(!enabled)}
              >
                {enabled ? 'disable' : 'enable'}
              </Btn>
            )}
            {onUninstall && (
              <Btn variant="danger" size="sm" disabled={busy} onClick={onUninstall}>
                uninstall
              </Btn>
            )}
          </div>
          <div className="flex items-center gap-2">
            {onUpdate && (
              <Btn variant="secondary" size="sm" disabled={busy} onClick={onUpdate}>
                update
              </Btn>
            )}
            {onInstall && (
              <Btn variant="secondary" size="sm" disabled={busy} onClick={onInstall}>
                install
              </Btn>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
