// desktop/src/renderer/components/chat/FiledNotice.tsx
import { useMoveChat, useProjects } from '../../lib/api/hooks';
import { useChat } from '../../stores/chat';
import { toast } from '../../stores/toast';
import { Lucide } from '../Lucide';

/** "Filed under Work / Atlas · Undo" — shown once after auto-filing moves the active chat. */
export function FiledNotice({ convId }: { convId: string }) {
  const loc = useChat((s) => s.filed[convId]);
  const clearFiled = useChat((s) => s.clearFiled);
  const projects = useProjects({ includeArchived: true });
  const move = useMoveChat();
  if (!loc?.context) return null;

  const projectName = loc.project
    ? (projects.data?.find((p) => p.context === loc.context && p.slug === loc.project)?.name ?? loc.project)
    : null;
  const label = projectName ? `${loc.context} / ${projectName}` : loc.context;

  const undo = () =>
    move.mutate(
      { id: convId, context: null, project: null, folder: null },
      {
        onSuccess: () => useChat.getState().markManualMove(convId),
        onError: (e) => toast.error(e.message),
      },
    );

  return (
    <div className="flex flex-shrink-0 items-center gap-2 border-b border-hairline px-6 py-[6px] font-mono text-11 text-ink-3">
      <Lucide name="folder-check" size={11} />
      <span>Filed under {label}</span>
      <span aria-hidden>·</span>
      <button type="button" onClick={undo} disabled={move.isPending} className="text-ink-2 underline-offset-2 hover:text-ink-0 hover:underline disabled:opacity-50">
        Undo
      </button>
      <button type="button" aria-label="dismiss" onClick={() => clearFiled(convId)} className="ml-auto text-ink-3 hover:text-ink-0">
        ×
      </button>
    </div>
  );
}
