import { useState } from 'react';
import { ApiError } from '../lib/api/client';
import { useExportConfluence, useImportSpaces } from '../lib/api/hooks';
import { toast } from '../stores/toast';
import { Btn } from './Btn';
import { Lucide } from './Lucide';

interface Props {
  jotId: string;
  defaultTitle: string;
  onClose: () => void;
}

// Module-level memory: remember the last export destination across opens.
// Not persisted to disk — acceptable for v1 since settings store integration
// would require a schema change. Resets on app restart.
let lastSpaceKey = '';
let lastParentId = '';

export function ConfluenceExportDialog({ jotId, defaultTitle, onClose }: Props) {
  const spaces = useImportSpaces();
  const exporter = useExportConfluence();

  const [spaceKey, setSpaceKey] = useState(() => lastSpaceKey);
  const [parentId, setParentId] = useState(() => lastParentId);
  // Non-null when the sidecar says the linked page no longer exists on Confluence.
  const [deletedRemotely, setDeletedRemotely] = useState(false);

  const spaceList = spaces.data ?? [];
  const resolvedSpaceKey = spaceKey || spaceList[0]?.key || '';

  function doExport(forceNew = false) {
    const key = resolvedSpaceKey;
    if (!key) return;
    lastSpaceKey = key;
    lastParentId = parentId;
    setDeletedRemotely(false);
    exporter.mutate(
      {
        jot_id: jotId,
        space_key: key,
        parent_id: parentId || undefined,
        title: defaultTitle,
        force_new: forceNew || undefined,
      },
      {
        onSuccess: (res) => {
          toast.success(`exported — ${res.action}`);
          // Open the page directly — toast has no action API.
          void window.gb.shell.openExternal(res.url);
          onClose();
        },
        onError: (err) => {
          const msg = err instanceof Error ? err.message : String(err);
          if (msg.includes('no longer exists')) {
            setDeletedRemotely(true);
          } else if (err instanceof ApiError && err.status === 404) {
            toast.error('jot not found');
          } else if (err instanceof ApiError && err.status === 502) {
            toast.error('confluence unreachable — check connection');
          } else {
            toast.error(`export failed: ${msg}`);
          }
        },
      },
    );
  }

  return (
    /* Overlay backdrop */
    <div
      role="dialog"
      aria-modal="true"
      aria-label="export to confluence"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        // Close on backdrop click, not on dialog content click.
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-[380px] rounded-r6 border border-hairline-2 bg-paper p-5 shadow-card">
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <span className="font-body text-13 font-medium text-ink-0">export to confluence</span>
          <button
            type="button"
            aria-label="close"
            onClick={onClose}
            className="rounded-sm p-[2px] text-ink-2 hover:text-ink-0"
          >
            <Lucide name="x" size={14} />
          </button>
        </div>

        {/* Space picker */}
        <label className="mb-1 block font-mono text-10 text-ink-2">space</label>
        {spaces.isLoading ? (
          <div className="mb-3 font-mono text-11 text-ink-3">loading spaces…</div>
        ) : spaces.isError ? (
          <div className="mb-3 font-mono text-11 text-oxblood">
            could not load spaces — check confluence connector
          </div>
        ) : spaceList.length === 0 ? (
          <div className="mb-3 font-mono text-11 text-ink-3">
            no monitored spaces — add confluence.spaces to routing.yaml
          </div>
        ) : (
          <select
            value={spaceKey || spaceList[0]?.key || ''}
            onChange={(e) => setSpaceKey(e.target.value)}
            className="mb-3 w-full rounded-r6 border border-hairline-2 bg-vellum px-3 py-[7px] text-13 text-ink-0 focus:outline-none"
          >
            {spaceList.map((s) => (
              <option key={`${s.site}:${s.key}`} value={s.key}>
                {s.name} ({s.key})
              </option>
            ))}
          </select>
        )}

        {/* Parent page id — plain text input since useConfluencePages needs a site
            arg we don't easily surface here; acceptable for v1. */}
        <label className="mb-1 block font-mono text-10 text-ink-2">
          parent page id <span className="text-ink-3">(optional)</span>
        </label>
        <input
          type="text"
          value={parentId}
          onChange={(e) => setParentId(e.target.value)}
          placeholder="leave blank to export at space root"
          className="mb-4 w-full rounded-r6 border border-hairline-2 bg-vellum px-3 py-[7px] text-13 text-ink-0 placeholder:text-ink-3 focus:border-ink-3 focus:outline-none"
        />

        {/* Deleted-remotely inline message */}
        {deletedRemotely && (
          <div className="mb-3 rounded-r6 border border-oxblood/30 bg-oxblood/10 px-3 py-2 text-12 text-oxblood">
            page was deleted on confluence
            <Btn
              variant="danger"
              size="sm"
              className="ml-3"
              disabled={exporter.isPending}
              onClick={() => doExport(true)}
            >
              export as new
            </Btn>
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-2">
          <Btn variant="ghost" size="sm" onClick={onClose} disabled={exporter.isPending}>
            cancel
          </Btn>
          <Btn
            variant="primary"
            size="sm"
            icon={<Lucide name="upload" size={13} />}
            disabled={exporter.isPending || spaceList.length === 0 || spaces.isError}
            onClick={() => doExport(false)}
          >
            {exporter.isPending ? 'exporting…' : 'export'}
          </Btn>
        </div>
      </div>
    </div>
  );
}
