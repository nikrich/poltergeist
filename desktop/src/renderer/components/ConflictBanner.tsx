import { useState } from 'react';
import { lineDiff } from '../lib/line-diff';
import type { Conflict } from '../lib/use-guarded-save';
import { Btn } from './Btn';
import { Lucide } from './Lucide';

interface Props {
  conflict: Conflict;
  resolving: boolean;
  onKeepMine: () => void;
  onKeepTheirs: () => void;
}

const lineClass = {
  same: 'text-ink-2',
  del: 'bg-oxblood/10 text-oxblood',
  add: 'bg-neon/10 text-ink-0',
} as const;
const prefix = { same: '  ', del: '- ', add: '+ ' } as const;

/** Spec B §7: autosave is paused; the user picks how to resolve. */
export function ConflictBanner({ conflict, resolving, onKeepMine, onKeepTheirs }: Props) {
  const [showDiff, setShowDiff] = useState(false);
  // Their version could not be re-read: there is nothing to diff or keep.
  const unread = conflict.unread === true;
  return (
    <div role="alert" className="sticky top-0 z-10 border-b border-hairline bg-vellum px-4 py-2 text-12 text-ink-1">
      <div className="flex items-center gap-2">
        <Lucide name="alert-triangle" size={14} color="var(--oxblood)" />
        <span className="flex-1">
          This note changed outside the editor. Autosave is paused — your text is kept.
        </span>
        {!unread && (
          <Btn variant="ghost" size="sm" onClick={() => setShowDiff((v) => !v)}>
            {showDiff ? 'hide changes' : 'view changes'}
          </Btn>
        )}
        <Btn variant="ghost" size="sm" onClick={onKeepTheirs} disabled={resolving || unread}>
          keep theirs
        </Btn>
        <Btn variant="primary" size="sm" onClick={onKeepMine} disabled={resolving}>
          keep mine
        </Btn>
      </div>
      {unread && (
        <div className="mt-1 text-11 text-ink-2">
          Their version could not be loaded, so only keep mine is available.
        </div>
      )}
      {showDiff && !unread && (
        <pre
          data-testid="conflict-diff"
          className="mt-2 max-h-64 overflow-auto rounded-sm border border-hairline bg-paper p-2 font-mono text-11"
        >
          <div className="mb-1 text-ink-3">- theirs (on disk) · + yours (in the editor)</div>
          {lineDiff(conflict.theirs, conflict.mine).map((line, i) => (
            <div key={i} className={lineClass[line.kind]}>
              {prefix[line.kind]}
              {line.text}
            </div>
          ))}
        </pre>
      )}
    </div>
  );
}
