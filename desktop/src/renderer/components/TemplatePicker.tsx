import { useState } from 'react';
import { useTemplates } from '../lib/api/hooks';
import type { TemplateCreateResponse, TemplateSummary } from '../../shared/api-types';
import { Btn } from './Btn';
import { Lucide } from './Lucide';
import { MakeTemplateDialog } from './MakeTemplateDialog';
import { TemplatePromptDialog } from './TemplatePromptDialog';

function firstError(t: TemplateSummary): string {
  const d = t.diagnostics.find((x) => x.severity === 'error');
  return d ? `line ${d.line}: ${d.message}` : 'template has errors';
}

/** Templates from 90-meta/templates; broken ones are shown disabled with ⚠. */
export function TemplateList({
  enabled = true,
  onPick,
}: {
  enabled?: boolean;
  onPick: (t: TemplateSummary) => void;
}) {
  const q = useTemplates({ enabled });
  if (q.isLoading) return <div className="px-3 py-2 font-mono text-11 text-ink-3">loading templates…</div>;
  if (q.isError) {
    return (
      <div role="alert" className="px-3 py-2 text-12 text-oxblood">
        templates unavailable — {q.error instanceof Error ? q.error.message : 'error'}
      </div>
    );
  }
  const items = q.data?.templates ?? [];
  if (items.length === 0) {
    return <div className="px-3 py-2 font-mono text-11 text-ink-3">no templates in 90-meta/templates</div>;
  }
  return (
    <ul role="menu" aria-label="templates">
      {items.map((t) => (
        <li key={t.id} role="none">
          <button
            type="button"
            role="menuitem"
            disabled={!t.valid}
            title={t.valid ? t.description : firstError(t)}
            onClick={() => onPick(t)}
            className="block w-full px-3 py-[6px] text-left text-12 text-ink-0 hover:bg-vellum disabled:cursor-not-allowed disabled:text-ink-3"
          >
            {!t.valid && <span aria-hidden="true">⚠ </span>}
            {t.name}
            {t.valid && t.description && (
              <span className="block text-11 text-ink-3">{t.description}</span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Jots screen: "template" button → list → prompt dialog → created note. */
export function TemplateMenu({ onCreated }: { onCreated: (res: TemplateCreateResponse) => void }) {
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<TemplateSummary | null>(null);
  const [makeWithAi, setMakeWithAi] = useState(false);
  return (
    <div className="relative">
      <Btn variant="ghost" size="sm" icon={<Lucide name="file-plus" size={13} />} onClick={() => setOpen((o) => !o)}>
        template
      </Btn>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-[260px] rounded-r6 border border-hairline-2 bg-paper py-1 shadow-card">
          <TemplateList
            enabled={open}
            onPick={(t) => {
              setOpen(false);
              setChosen(t);
            }}
          />
          <div className="mt-1 border-t border-hairline pt-1">
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setMakeWithAi(true);
              }}
              className="block w-full px-3 py-[6px] text-left text-12 text-ink-1 hover:bg-vellum"
            >
              make one with ai…
            </button>
          </div>
        </div>
      )}
      {makeWithAi && <MakeTemplateDialog onClose={() => setMakeWithAi(false)} />}
      {chosen && (
        <TemplatePromptDialog
          key={chosen.id}
          template={chosen}
          mode="create"
          onClose={() => setChosen(null)}
          onCreated={onCreated}
        />
      )}
    </div>
  );
}

/** `/template` in the editor: pick a template, answer, insert its body. */
export function TemplateInsertDialog({
  onClose,
  onInsert,
}: {
  onClose: () => void;
  onInsert: (markdown: string) => void;
}) {
  const [chosen, setChosen] = useState<TemplateSummary | null>(null);
  if (chosen) {
    return (
      <TemplatePromptDialog key={chosen.id} template={chosen} mode="insert" onClose={onClose} onInsert={onInsert} />
    );
  }
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="insert template"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-[320px] rounded-r6 border border-hairline-2 bg-paper py-2 shadow-card">
        <div className="mb-1 flex items-center justify-between px-3">
          <span className="font-body text-13 font-medium text-ink-0">insert template</span>
          <button type="button" aria-label="close" onClick={onClose}
            className="rounded-sm p-[2px] text-ink-2 hover:text-ink-0">
            <Lucide name="x" size={14} />
          </button>
        </div>
        <TemplateList onPick={setChosen} />
      </div>
    </div>
  );
}
