import { useState } from 'react';
import { useRestoreVersion } from '../lib/api/hooks';
import type { HistoryEntry } from '../../shared/api-types';
import { Btn } from './Btn';
import type { GuardHandle } from './GuardedNoteEditor';
import { HistoryDrawer } from './HistoryDrawer';
import { Lucide } from './Lucide';

interface Props {
  /** Vault-relative path of the open note; null hides the button. */
  path: string | null;
  /** The open editor's guard: restore runs between its autosaves and reloads it. */
  guardRef: React.MutableRefObject<GuardHandle | null>;
}

/** "History" item for an editor header. Parents key it by path so switching notes closes the drawer. */
export function NoteHistoryButton({ path, guardRef }: Props) {
  const [open, setOpen] = useState(false);
  const restoreVersion = useRestoreVersion();
  if (path === null) return null;

  const onRestore = async (entry: HistoryEntry): Promise<void> => {
    const guard = guardRef.current;
    if (!guard) throw new Error('the editor is still loading');
    await guard.restore(() => restoreVersion.mutateAsync({ path, blob: entry.blob }));
  };

  return (
    <>
      <Btn
        variant="ghost"
        size="sm"
        icon={<Lucide name="history" size={13} />}
        onClick={() => setOpen(true)}
      >
        history
      </Btn>
      {open && <HistoryDrawer path={path} onClose={() => setOpen(false)} onRestore={onRestore} />}
    </>
  );
}
