import { useEffect, useMemo, useRef, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { keymap, type EditorView } from '@codemirror/view';
import { Prec } from '@codemirror/state';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '../lib/api/client';
import { useContexts } from '../lib/api/hooks';
import {
  lintTemplate,
  saveTemplateSource,
  useTemplateFunctions,
  useTemplateQueryValues,
  useTemplateSource,
} from '../lib/api/template-editor';
import { EMPTY_HINTS, type TemplateEditorData } from '../lib/template-editor/completions';
import { templateEditorExtensions } from '../lib/template-editor/extensions';
import { registerNavigationGuard } from '../stores/navigation';
import { toast } from '../stores/toast';
import { Btn } from './Btn';
import { Lucide } from './Lucide';
import { TemplateTestRun } from './TemplateTestRun';

export const DISCARD_TEMPLATE_PROMPT = 'Discard your unsaved template changes?';

interface Props {
  templateId: string;
  /** Told whenever the text starts or stops differing from the saved file. */
  onDirtyChange?: (dirty: boolean) => void;
  /** Called once with the CodeMirror view; tests drive edits through it. */
  onCreateEditor?: (view: EditorView) => void;
}

/** Spec C3: CodeMirror over a template file with registry-driven
 * completions, hover docs and lint, explicit save with an etag, and a
 * Test run pane. */
export function TemplateSourceEditor({ templateId, onDirtyChange, onCreateEditor }: Props) {
  const qc = useQueryClient();
  const src = useTemplateSource(templateId);
  const fns = useTemplateFunctions();
  const values = useTemplateQueryValues();
  const contexts = useContexts();
  const [value, setValue] = useState<string | null>(null);
  const [etag, setEtag] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [showRun, setShowRun] = useState(false);
  const dirty = value !== null && saved !== null && value !== saved;

  const data = useRef<TemplateEditorData>({ registry: null, hints: EMPTY_HINTS });
  useEffect(() => {
    data.current = {
      registry: fns.data ?? null,
      hints: {
        types: values.data?.types ?? [],
        statuses: values.data?.statuses ?? [],
        contexts: contexts.data?.contexts ?? [],
      },
    };
  }, [fns.data, values.data, contexts.data]);

  useEffect(() => {
    if (src.data && value === null) {
      setValue(src.data.source);
      setSaved(src.data.source);
      setEtag(src.data.etag);
    }
  }, [src.data, value]);

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;
  useEffect(
    () =>
      registerNavigationGuard('screen', () => !dirtyRef.current || window.confirm(DISCARD_TEMPLATE_PROMPT)),
    [],
  );

  async function save(overwrite = false) {
    if (value === null || saving) return;
    setSaving(true);
    try {
      const res = await saveTemplateSource(templateId, value, overwrite ? null : etag);
      setSaved(value);
      setEtag(res.etag);
      setConflict(false);
      void qc.invalidateQueries({ queryKey: ['templates'] });
      toast.success(res.status === 'pending' ? 'template saved for approval' : 'template saved');
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflict(true);
      else toast.error(`could not save template: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  }

  async function reload() {
    const res = await src.refetch();
    if (res.data) {
      setValue(res.data.source);
      setSaved(res.data.source);
      setEtag(res.data.etag);
      setConflict(false);
    }
  }

  const saveRef = useRef(save);
  saveRef.current = save;
  const extensions = useMemo(
    () => [
      ...templateEditorExtensions(() => data.current, lintTemplate),
      Prec.high(
        keymap.of([
          {
            key: 'Mod-s',
            run: () => {
              void saveRef.current();
              return true;
            },
          },
        ]),
      ),
    ],
    [],
  );

  if (src.isError) {
    return (
      <div role="alert" className="p-4 text-12 text-oxblood">
        could not open template — {src.error instanceof Error ? src.error.message : 'error'}
      </div>
    );
  }
  if (value === null) return <div className="p-4 font-mono text-11 text-ink-3">loading template…</div>;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex flex-shrink-0 items-center gap-2 border-b border-hairline px-4 py-2">
        <span className="font-mono text-11 text-ink-2">{src.data?.path}</span>
        {dirty && <span className="font-mono text-10 text-ink-3">unsaved</span>}
        <div className="flex-1" />
        <Btn
          variant={showRun ? 'secondary' : 'ghost'}
          size="sm"
          icon={<Lucide name="play" size={13} />}
          onClick={() => setShowRun((s) => !s)}
        >
          test run
        </Btn>
        <Btn variant="primary" size="sm" onClick={() => void save()} disabled={!dirty || saving}>
          {saving ? 'saving…' : 'save'}
        </Btn>
      </div>
      {conflict && (
        <div role="alert" className="flex flex-shrink-0 items-center gap-2 bg-oxblood/10 px-4 py-2 text-12 text-ink-0">
          <span className="flex-1">this template changed outside the editor. your text is not saved.</span>
          <Btn variant="ghost" size="sm" onClick={() => void reload()}>
            reload theirs
          </Btn>
          <Btn variant="danger" size="sm" onClick={() => void save(true)}>
            keep mine
          </Btn>
        </div>
      )}
      <div className="flex flex-1 overflow-hidden">
        <div className="min-w-0 flex-1 overflow-auto">
          <CodeMirror
            value={value}
            extensions={extensions}
            basicSetup={{ lineNumbers: true, foldGutter: false, autocompletion: false }}
            onChange={setValue}
            onCreateEditor={onCreateEditor}
            theme="dark"
            className="h-full text-13"
          />
        </div>
        {showRun && (
          <div className="w-1/2 min-w-0 border-l border-hairline">
            <TemplateTestRun templateId={templateId} source={value} />
          </div>
        )}
      </div>
    </div>
  );
}
