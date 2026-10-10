import { useEffect, useMemo, useRef, useState } from 'react';
import {
  useContexts,
  useCreateFromTemplate,
  useProjects,
  useRenderTemplate,
} from '../lib/api/hooks';
import {
  createLatestFetcher,
  fetchSuggestions,
  type SuggestResult,
} from '../lib/editor/link-suggest';
import type {
  Project,
  SuggestItem,
  TemplateCreateResponse,
  TemplatePrompt,
  TemplateSummary,
} from '../../shared/api-types';
import { Btn } from './Btn';
import { Lucide } from './Lucide';

/** A dialog may wait longer than the inline 300 ms editor suggest. */
const PERSON_SUGGEST_TIMEOUT_MS = 1500;
const INPUT =
  'mb-3 w-full rounded-r6 border bg-vellum px-3 py-[7px] text-13 text-ink-0 placeholder:text-ink-3 focus:border-ink-3 focus:outline-none';
const FIELD_ERROR_RE = /^([a-z][a-z0-9_]*): ([\s\S]*)$/;

interface DialogError {
  field: string | null;
  message: string;
}

/** Field errors arrive as `"<field>: <message>"`. A pydantic body rejection's
 * list detail reaches us as a raw JSON envelope; anything not a plain string
 * message degrades to a general error instead of leaking JSON or crashing. */
function dialogError(err: unknown, fieldIds: string[], mode: 'create' | 'insert'): DialogError {
  const general: DialogError = {
    field: null,
    message:
      mode === 'create'
        ? 'could not create the note from this template'
        : 'could not render this template',
  };
  const raw: unknown = err instanceof Error ? err.message : err;
  const message = typeof raw === 'string' ? raw.trim() : '';
  if (!message || message.startsWith('{') || message.startsWith('[')) return general;
  const m = FIELD_ERROR_RE.exec(message);
  const field = m && fieldIds.includes(m[1]!) ? m[1]! : null;
  return { field, message };
}

export function todayIso(now: Date = new Date()): string {
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${m}-${d}`;
}

/** The template's prompts plus the implicit context/project pickers it needs. */
export function dialogFields(template: TemplateSummary): TemplatePrompt[] {
  const ids = new Set(template.prompts.map((p) => p.id));
  const extra: TemplatePrompt[] = [];
  if (template.variables.includes('context') && !ids.has('context')) {
    extra.push({
      id: 'context',
      ask: 'Context',
      type: 'context',
      optional: false,
      default: null,
      options: [],
    });
  }
  if (template.variables.includes('project') && !ids.has('project')) {
    extra.push({
      id: 'project',
      ask: 'Project',
      type: 'project',
      optional: true,
      default: null,
      options: [],
    });
  }
  return [...template.prompts, ...extra];
}

function initialValue(f: TemplatePrompt): string {
  if (f.default !== null) return f.default;
  if (f.type === 'date') return todayIso();
  if (f.type === 'choice') return f.options[0] ?? '';
  return '';
}

interface PersonFieldProps {
  inputId: string;
  /** Starting text, e.g. the prompt's default, so the input shows what will be submitted. */
  initial: string;
  invalid: boolean;
  onChange: (value: string) => void;
  suggest: (query: string) => Promise<SuggestResult>;
}

function PersonField({ inputId, initial, invalid, onChange, suggest }: PersonFieldProps) {
  const [text, setText] = useState(initial);
  const [items, setItems] = useState<SuggestItem[]>([]);
  const latest = useRef('');

  async function onType(q: string) {
    setText(q);
    onChange(q);
    latest.current = q;
    if (!q.trim()) {
      setItems([]);
      return;
    }
    const res = await suggest(q);
    if (latest.current === q) setItems(res.items.filter((i) => i.path !== null));
  }

  function pick(item: SuggestItem) {
    latest.current = '';
    setText(item.label);
    onChange(item.path!);
    setItems([]);
  }

  return (
    <div className="relative">
      <input
        id={inputId}
        type="text"
        role="combobox"
        aria-expanded={items.length > 0}
        aria-autocomplete="list"
        aria-invalid={invalid}
        value={text}
        onChange={(e) => void onType(e.target.value)}
        placeholder="a name, or pick their page"
        className={`${INPUT} ${invalid ? 'border-oxblood' : 'border-hairline-2'}`}
      />
      {items.length > 0 && (
        <ul className="absolute left-0 right-0 top-[38px] z-10 max-h-[180px] overflow-y-auto rounded-r6 border border-hairline-2 bg-paper py-1 shadow-card">
          {items.map((item) => (
            <li key={item.path!}>
              <button
                type="button"
                onClick={() => pick(item)}
                className="block w-full px-3 py-1 text-left text-12 text-ink-0 hover:bg-vellum"
              >
                {item.label}
                <span className="ml-2 font-mono text-10 text-ink-3">{item.detail}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface Props {
  template: TemplateSummary;
  mode: 'create' | 'insert';
  onClose: () => void;
  onCreated?: (res: TemplateCreateResponse) => void;
  onInsert?: (markdown: string) => void;
}

export function TemplatePromptDialog({ template, mode, onClose, onCreated, onInsert }: Props) {
  const fields = useMemo(() => dialogFields(template), [template]);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.id, initialValue(f)])),
  );
  const [error, setError] = useState<DialogError | null>(null);
  const contexts = useContexts().data?.contexts ?? [];
  const projectsQuery = useProjects();
  const projects: Project[] = Array.isArray(projectsQuery.data) ? projectsQuery.data : [];
  const create = useCreateFromTemplate();
  const renderTpl = useRenderTemplate();
  const pending = create.isPending || renderTpl.isPending;
  const peopleFetcher = useMemo(
    () => createLatestFetcher((kind, q) => fetchSuggestions(kind, q, PERSON_SUGGEST_TIMEOUT_MS)),
    [],
  );

  useEffect(() => {
    // Capture phase on window runs before any bubbling listener (the note
    // view's own Escape handling included); swallowing the key there means
    // Escape closes only this dialog, and never the view behind it mid-submit.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      if (!pending) onClose();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [pending, onClose]);

  const effective = (f: TemplatePrompt): string => {
    const v = values[f.id] ?? '';
    if (f.type === 'context' && !v && !f.optional) return contexts[0] ?? '';
    return v;
  };
  const missing = fields.filter((f) => !f.optional && !effective(f).trim());
  const set = (id: string, v: string) => setValues((prev) => ({ ...prev, [id]: v }));

  function submit() {
    if (missing.length > 0 || pending) return;
    const answers: Record<string, string> = {};
    for (const f of fields) {
      const v = effective(f).trim();
      if (v) answers[f.id] = v;
    }
    setError(null);
    const onError = (err: unknown) => {
      setError(
        dialogError(
          err,
          fields.map((f) => f.id),
          mode,
        ),
      );
    };
    if (mode === 'create') {
      create.mutate(
        { id: template.id, answers },
        {
          onSuccess: (res) => {
            onCreated?.(res);
            onClose();
          },
          onError,
        },
      );
    } else {
      renderTpl.mutate(
        { id: template.id, answers },
        {
          onSuccess: (res) => {
            onInsert?.(res.body);
            onClose();
          },
          onError,
        },
      );
    }
  }

  function control(f: TemplatePrompt) {
    const inputId = `tpl-${template.id}-${f.id}`;
    const invalid = error?.field === f.id;
    const cls = `${INPUT} ${invalid ? 'border-oxblood' : 'border-hairline-2'}`;
    switch (f.type) {
      case 'person':
        return (
          <PersonField
            inputId={inputId}
            initial={values[f.id] ?? ''}
            invalid={invalid}
            onChange={(v) => set(f.id, v)}
            suggest={(q) => peopleFetcher('person', q)}
          />
        );
      case 'date':
        return (
          <input
            id={inputId}
            type="date"
            aria-invalid={invalid}
            value={effective(f)}
            onChange={(e) => set(f.id, e.target.value)}
            className={cls}
          />
        );
      case 'choice':
        return (
          <select
            id={inputId}
            aria-invalid={invalid}
            value={effective(f)}
            onChange={(e) => set(f.id, e.target.value)}
            className={cls}
          >
            {f.options.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        );
      case 'context':
        return (
          <select
            id={inputId}
            aria-invalid={invalid}
            value={effective(f)}
            onChange={(e) => set(f.id, e.target.value)}
            className={cls}
          >
            {f.optional && <option value="">—</option>}
            {contexts.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        );
      case 'project':
        return (
          <select
            id={inputId}
            aria-invalid={invalid}
            value={effective(f)}
            onChange={(e) => set(f.id, e.target.value)}
            className={cls}
          >
            <option value="">none</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{`${p.context} / ${p.name}`}</option>
            ))}
          </select>
        );
      default:
        return (
          <input
            id={inputId}
            type="text"
            aria-invalid={invalid}
            value={effective(f)}
            onChange={(e) => set(f.id, e.target.value)}
            className={cls}
          />
        );
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`new from template ${template.name}`}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget && !pending) onClose();
      }}
    >
      <form
        className="w-[420px] rounded-r6 border border-hairline-2 bg-paper p-5 shadow-card"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="mb-4 flex items-center justify-between">
          <span className="font-body text-13 font-medium text-ink-0">{template.name}</span>
          <button
            type="button"
            aria-label="close"
            onClick={onClose}
            className="rounded-sm p-[2px] text-ink-2 hover:text-ink-0"
          >
            <Lucide name="x" size={14} />
          </button>
        </div>
        {fields.map((f) => (
          <div key={f.id}>
            <label
              htmlFor={`tpl-${template.id}-${f.id}`}
              className="mb-1 block font-mono text-10 text-ink-2"
            >
              {f.ask}
              {f.optional ? ' (optional)' : ''}
            </label>
            {control(f)}
          </div>
        ))}
        {error && (
          <div role="alert" className="mb-3 text-12 text-oxblood">
            {error.message}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Btn variant="ghost" size="sm" onClick={onClose}>
            cancel
          </Btn>
          <Btn variant="primary" size="sm" type="submit" disabled={missing.length > 0 || pending}>
            {mode === 'create' ? 'create' : 'insert'}
          </Btn>
        </div>
      </form>
    </div>
  );
}
