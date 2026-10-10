import { useState } from 'react';
import { MAX_TEMPLATE_DESCRIPTION, useGenerateTemplate } from '../lib/api/template-ai';
import { useNavigation } from '../stores/navigation';
import { toast } from '../stores/toast';
import { Btn } from './Btn';
import { Lucide } from './Lucide';

/** Spec C4 "Make one with AI": describe a template, the sidecar drafts and
 * validates it, and a valid draft waits on the Changes screen for approval.
 * Nothing here applies a template. */
export function MakeTemplateDialog({ onClose }: { onClose: () => void }) {
  const [description, setDescription] = useState('');
  const gen = useGenerateTemplate();
  const setActive = useNavigation((s) => s.setActive);
  const result = gen.data;

  function copyDraft(draft: string) {
    void navigator.clipboard
      .writeText(draft)
      .then(() => toast.info('draft copied'))
      .catch(() => toast.error('could not copy the draft'));
  }

  function openChanges() {
    setActive('changes');
    // A navigation guard (e.g. unsaved template edits) may cancel the switch;
    // the dialog then stays open so the result is not lost.
    if (useNavigation.getState().active === 'changes') onClose();
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="make a template with ai"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex max-h-[80vh] w-[480px] flex-col gap-3 overflow-auto rounded-r6 border border-hairline-2 bg-paper p-4 shadow-card">
        <div className="flex items-center justify-between">
          <span className="font-body text-13 font-medium text-ink-0">make a template with ai</span>
          <button type="button" aria-label="close" onClick={onClose} className="rounded-sm p-[2px] text-ink-2 hover:text-ink-0">
            <Lucide name="x" size={14} />
          </button>
        </div>
        <textarea
          aria-label="describe the template"
          value={description}
          maxLength={MAX_TEMPLATE_DESCRIPTION}
          rows={4}
          placeholder="e.g. a weekly review with wins, misses and open follow-ups"
          onChange={(e) => setDescription(e.target.value)}
          className="w-full rounded-sm border border-hairline-2 bg-vellum px-2 py-1 text-12 text-ink-0"
        />
        <div className="flex justify-end gap-2">
          <Btn variant="ghost" size="sm" onClick={onClose}>
            cancel
          </Btn>
          <Btn
            variant="primary"
            size="sm"
            icon={<Lucide name="sparkles" size={13} />}
            disabled={!description.trim() || gen.isPending}
            onClick={() => gen.mutate(description.trim())}
          >
            {gen.isPending ? 'drafting…' : 'generate'}
          </Btn>
        </div>
        {gen.isPending && (
          <p role="status" className="text-12 text-ink-2">
            drafting your template — this can take a minute.
          </p>
        )}
        {gen.isError && (
          <p role="alert" className="text-12 text-oxblood">
            could not make a template — {gen.error instanceof Error ? gen.error.message : 'error'}
          </p>
        )}
        {result?.status === 'pending' && (
          <div role="status" className="flex flex-col gap-2 text-12 text-ink-1">
            <p>
              {`“${result.name}” is pending your approval on the changes screen. It is not used until you approve it.`}
            </p>
            <Btn variant="secondary" size="sm" onClick={openChanges}>
              open changes
            </Btn>
          </div>
        )}
        {result?.status === 'invalid' && (
          <div role="alert" className="flex flex-col gap-2 text-12">
            <p className="text-oxblood">{`the ai draft did not pass validation, so nothing was saved: ${result.message}`}</p>
            <ul aria-label="problems" className="list-disc pl-4 text-ink-1">
              {result.diagnostics.map((d, i) => (
                <li key={i}>{`line ${d.line}: ${d.message}`}</li>
              ))}
            </ul>
            <pre aria-label="ai draft" className="max-h-[200px] overflow-auto whitespace-pre-wrap rounded-sm bg-vellum p-2 font-mono text-11 text-ink-0">
              {result.draft}
            </pre>
            <Btn variant="ghost" size="sm" onClick={() => copyDraft(result.draft)}>
              copy draft
            </Btn>
          </div>
        )}
      </div>
    </div>
  );
}
