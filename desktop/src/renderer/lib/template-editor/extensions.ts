import { autocompletion } from '@codemirror/autocomplete';
import { markdown } from '@codemirror/lang-markdown';
import type { Extension } from '@codemirror/state';
import { templateCompletions, type TemplateEditorData } from './completions';
import { templateHover } from './hover';
import { templateLinter, type FetchLint } from './lint';

/** Everything the template editor adds to CodeMirror. `getData` is read on
 * every request, so registry and hints can load after the editor mounts. */
export function templateEditorExtensions(
  getData: () => TemplateEditorData,
  fetchLint: FetchLint,
): Extension[] {
  return [
    markdown(),
    autocompletion({ override: [templateCompletions(getData)] }),
    templateHover(getData),
    templateLinter(fetchLint),
  ];
}
