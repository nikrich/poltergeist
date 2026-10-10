import { useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { MakeTemplateDialog } from '../components/MakeTemplateDialog';
import { DISCARD_TEMPLATE_PROMPT, TemplateSourceEditor } from '../components/TemplateSourceEditor';
import { useTemplates } from '../lib/api/hooks';
import { useCreateBlankTemplate } from '../lib/api/template-editor';
import { toast } from '../stores/toast';

/** Spec C3 "Templates screen (a tab in the jots screen)": list, create
 * blank, open the template editor. Broken templates open too — editing is
 * how they get fixed. */
export function TemplatesPanel({ onBack }: { onBack: () => void }) {
  const list = useTemplates();
  const createBlank = useCreateBlankTemplate();
  const [selected, setSelected] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [newName, setNewName] = useState<string | null>(null);
  const [makeWithAi, setMakeWithAi] = useState(false);

  function leaveOk(): boolean {
    return !dirty || window.confirm(DISCARD_TEMPLATE_PROMPT);
  }

  function select(id: string) {
    if (id === selected || !leaveOk()) return;
    setDirty(false);
    setSelected(id);
  }

  function submitNew() {
    const name = (newName ?? '').trim();
    if (!name || !leaveOk()) return;
    createBlank.mutate(name, {
      onSuccess: (res) => {
        setNewName(null);
        setDirty(false);
        setSelected(res.id);
      },
      onError: (err) => toast.error(`could not create template: ${err.message}`),
    });
  }

  const items = list.data?.templates ?? [];
  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar
        title="templates"
        subtitle="90-meta/templates"
        right={
          <div className="flex gap-2">
            <Btn
              variant="ghost"
              size="sm"
              ariaLabel="back to jots"
              icon={<Lucide name="arrow-left" size={13} />}
              onClick={() => {
                if (leaveOk()) onBack();
              }}
            >
              jots
            </Btn>
            <Btn variant="ghost" size="sm" icon={<Lucide name="sparkles" size={13} />} onClick={() => setMakeWithAi(true)}>
              make one with ai
            </Btn>
            <Btn variant="primary" size="sm" icon={<Lucide name="plus" size={13} />} onClick={() => setNewName('')}>
              new template
            </Btn>
          </div>
        }
      />
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-[260px] flex-shrink-0 overflow-auto border-r border-hairline py-2">
          {newName !== null && (
            <form
              className="flex gap-1 px-3 pb-2"
              onSubmit={(e) => {
                e.preventDefault();
                submitNew();
              }}
            >
              <input
                autoFocus
                aria-label="template name"
                value={newName}
                maxLength={80}
                onChange={(e) => setNewName(e.target.value)}
                className="min-w-0 flex-1 rounded-sm border border-hairline-2 bg-vellum px-2 py-1 text-12 text-ink-0"
              />
              <Btn type="submit" size="sm" disabled={!newName.trim() || createBlank.isPending}>
                create
              </Btn>
            </form>
          )}
          {list.isLoading && <p className="px-3 font-mono text-11 text-ink-3">loading templates…</p>}
          {list.isError && (
            <p role="alert" className="px-3 text-12 text-oxblood">
              templates unavailable
            </p>
          )}
          <ul aria-label="templates">
            {items.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  aria-label={`edit template ${t.name}`}
                  aria-current={t.id === selected ? 'true' : undefined}
                  onClick={() => select(t.id)}
                  className="block w-full px-3 py-[6px] text-left text-12 text-ink-0 hover:bg-vellum aria-[current=true]:bg-vellum"
                >
                  {!t.valid && <span aria-hidden="true">⚠ </span>}
                  {t.name}
                  <span className="block font-mono text-10 text-ink-3">{t.id}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <section className="min-w-0 flex-1">
          {selected ? (
            <TemplateSourceEditor key={selected} templateId={selected} onDirtyChange={setDirty} />
          ) : (
            <p className="p-4 text-12 text-ink-3">pick a template to edit, or make a new one.</p>
          )}
        </section>
      </div>
      {makeWithAi && <MakeTemplateDialog onClose={() => setMakeWithAi(false)} />}
    </div>
  );
}
