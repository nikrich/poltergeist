import { useEffect, useRef, useState } from 'react';
import { useTemplateDryRun } from '../lib/api/template-editor';
import { extractPrompts } from '../lib/template-editor/analyze';
import { initialAnswers } from '../lib/templates/last-answers';
import type { TemplateDryRunResponse } from '../../shared/api-types';
import { Btn } from './Btn';
import { RichMarkdownEditor } from './RichMarkdownEditor';

const noop = () => {};

/** Spec C3 Test run: render the editor's current text with sample answers
 * (last real answers first) and show the result through the normal rich
 * renderer, read-only, with the target path. Nothing is written. */
export function TemplateTestRun({ templateId, source }: { templateId: string; source: string }) {
  const run = useTemplateDryRun();
  const [answers, setAnswers] = useState<Record<string, string>>(() =>
    initialAnswers(
      templateId,
      extractPrompts(source).map((p) => p.id),
    ),
  );
  const [result, setResult] = useState<TemplateDryRunResponse | null>(null);
  const [runs, setRuns] = useState(0);

  function go(next: Record<string, string>) {
    run.mutate(
      { source, answers: next, id: templateId },
      {
        onSuccess: (res) => {
          setResult(res);
          setAnswers(res.ok ? res.answers : { ...res.answers, ...next });
          setRuns((n) => n + 1);
        },
      },
    );
  }

  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    go(answers);
  });

  const prompts = result?.prompts ?? [];
  return (
    <div className="flex h-full flex-col overflow-hidden" aria-label="test run">
      <div className="flex-shrink-0 border-b border-hairline px-4 py-3">
        {prompts.map((p) => (
          <label key={p.id} className="mb-2 block text-12 text-ink-1">
            {p.ask}
            <input
              aria-label={p.ask}
              value={answers[p.id] ?? ''}
              placeholder={p.optional ? 'optional' : ''}
              onChange={(e) => setAnswers((a) => ({ ...a, [p.id]: e.target.value }))}
              className="mt-1 block w-full rounded-sm border border-hairline-2 bg-vellum px-2 py-1 text-12 text-ink-0"
            />
          </label>
        ))}
        <Btn variant="secondary" size="sm" onClick={() => go(answers)} disabled={run.isPending}>
          {run.isPending ? 'rendering…' : 'run again'}
        </Btn>
      </div>
      <div className="flex-1 overflow-auto px-4 py-3">
        {run.isError && (
          <p role="alert" className="text-12 text-oxblood">
            test run failed — {run.error instanceof Error ? run.error.message : 'error'}
          </p>
        )}
        {result?.error && (
          <p role="alert" className="text-12 text-oxblood">
            {result.error}
          </p>
        )}
        {result?.wouldBeFiledAt && (
          <p className="mb-2 font-mono text-11 text-ink-2">
            would be filed at <code>{result.wouldBeFiledAt}</code>
          </p>
        )}
        {result?.rendered && (
          <RichMarkdownEditor
            key={runs}
            markdown={result.rendered.body}
            onSave={noop}
            readOnly
            jotId={`template-preview-${templateId}`}
          />
        )}
      </div>
    </div>
  );
}
