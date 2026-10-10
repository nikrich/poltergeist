import { linter, type Diagnostic } from '@codemirror/lint';
import type { Text } from '@codemirror/state';
import type { EditorView } from '@codemirror/view';
import type { TemplateDiagnostic } from '../../../shared/api-types';

/** Spec C3: lint via /v1/templates/lint, debounced 500 ms. */
export const TEMPLATE_LINT_DELAY_MS = 500;

export type FetchLint = (source: string) => Promise<TemplateDiagnostic[]>;

/** Server diagnostics (1-based line/col, whole file) → CodeMirror ranges.
 * A range covers the `{{ … }}` at that spot, else the word, else one char. */
export function toCmDiagnostics(doc: Text, diags: TemplateDiagnostic[]): Diagnostic[] {
  return diags.map((d) => {
    const line = doc.line(Math.min(Math.max(d.line, 1), doc.lines));
    const from = Math.min(line.from + Math.max(d.col - 1, 0), line.to);
    const rest = doc.sliceString(from, line.to);
    let to = from;
    if (rest.startsWith('{{')) {
      const close = rest.indexOf('}}');
      to = close >= 0 ? from + close + 2 : line.to;
    } else {
      const word = /^[^\s:]+/.exec(rest);
      to = word ? from + word[0].length : Math.min(from + 1, line.to);
    }
    return { from, to, severity: d.severity, message: d.message, source: 'template' };
  });
}

/** A CodeMirror lint source. A failed request shows no markers rather than
 * stale or invented ones. */
export function templateLintSource(fetchLint: FetchLint) {
  return async (view: Pick<EditorView, 'state'>): Promise<Diagnostic[]> => {
    const doc = view.state.doc;
    try {
      return toCmDiagnostics(doc, await fetchLint(doc.toString()));
    } catch {
      return [];
    }
  };
}

export function templateLinter(fetchLint: FetchLint) {
  return linter(templateLintSource(fetchLint), { delay: TEMPLATE_LINT_DELAY_MS });
}
