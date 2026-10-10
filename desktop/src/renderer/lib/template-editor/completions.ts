import type {
  Completion,
  CompletionContext,
  CompletionResult,
  CompletionSource,
} from '@codemirror/autocomplete';
import type { TemplateFunctionSpec, TemplateRegistry } from '../../../shared/api-types';
import { cursorContext, extractPrompts, type CursorContext, type PromptInfo } from './analyze';

/** Values the query completions offer that do not live in the registry. */
export interface QueryValueHints {
  types: string[];
  statuses: string[];
  contexts: string[];
}

export interface TemplateEditorData {
  registry: TemplateRegistry | null;
  hints: QueryValueHints;
}

export const EMPTY_HINTS: QueryValueHints = { types: [], statuses: [], contexts: [] };
export const SORT_VALUES = ['created desc', 'created asc', 'updated desc', 'updated asc'];

/** The registry doc string, plus its example: what every completion and hover shows. */
export function specInfo(spec: TemplateFunctionSpec): string {
  return spec.example ? `${spec.doc}\n\nExample: ${spec.example}` : spec.doc;
}

/** The value type a dotted name resolves to, e.g. ['person'] → 'person',
 * ['now', 'date'] → 'date'; null when any step is unknown, including a
 * prompt whose type the registry does not list. */
export function valueTypeOf(
  path: string[],
  prompts: PromptInfo[],
  reg: TemplateRegistry,
): string | null {
  const [root, ...rest] = path;
  if (root === undefined) return null;
  const prompt = prompts.find((p) => p.id === root);
  let type: string | null = prompt
    ? (reg.promptTypes.find((t) => t.name === prompt.type)?.type ?? null)
    : (reg.variables.find((v) => v.name === root)?.type ?? null);
  for (const name of rest) {
    if (type === null) return null;
    const owner: string = type;
    type = reg.fields.find((f) => f.owner === owner && f.name === name)?.type ?? null;
  }
  return type;
}

function fromSpec(spec: TemplateFunctionSpec, type: string, apply?: string): Completion {
  return { label: spec.name, type, detail: spec.type, info: specInfo(spec), apply };
}

function uniq(values: string[]): string[] {
  return [...new Set(values.filter((v) => v.trim() !== ''))];
}

function queryValues(key: string, hints: QueryValueHints): string[] {
  if (key === 'status') return uniq(['open', ...hints.statuses]);
  if (key === 'sort') return SORT_VALUES;
  if (key === 'type') return uniq(hints.types);
  if (key === 'context') return uniq(hints.contexts);
  return [];
}

export function optionsFor(
  cur: CursorContext,
  text: string,
  reg: TemplateRegistry,
  hints: QueryValueHints,
): Completion[] {
  switch (cur.kind) {
    case 'variable': {
      const prompts = extractPrompts(text);
      const own = prompts.map<Completion>((p) => {
        const typeSpec = reg.promptTypes.find((t) => t.name === p.type);
        return {
          label: p.id,
          type: 'variable',
          detail: `prompt · ${p.type}`,
          info: `Your template's own prompt \`${p.id}\`.${typeSpec ? `\n\n${specInfo(typeSpec)}` : ''}`,
          boost: 2,
        };
      });
      const ids = new Set(prompts.map((p) => p.id));
      return [
        ...own,
        ...reg.variables.filter((v) => !ids.has(v.name)).map((v) => fromSpec(v, 'variable')),
      ];
    }
    case 'field': {
      const owner = valueTypeOf(cur.ownerPath, extractPrompts(text), reg);
      return owner === null
        ? []
        : reg.fields.filter((f) => f.owner === owner).map((f) => fromSpec(f, 'property'));
    }
    case 'filter':
      return reg.filters.map((f) => fromSpec(f, 'function', f.argRequired ? `${f.name}: ` : f.name));
    case 'prompt-type':
      return reg.promptTypes.map((t) => fromSpec(t, 'type'));
    case 'query-key':
      return (reg.queryKeys ?? []).map((k) => fromSpec(k, 'keyword', `${k.name}: `));
    case 'query-value': {
      const spec = (reg.queryKeys ?? []).find((k) => k.name === cur.key);
      if (!spec) return [];
      return queryValues(cur.key, hints).map<Completion>((v) => ({
        label: v,
        type: 'constant',
        detail: cur.key,
        info: specInfo(spec),
      }));
    }
  }
}

/** Completions after `{{`, after `|`, for prompt `type:`, and inside ```query
 * fences, all from the C1 registry (query keys only when C2 added them). */
export function templateCompletions(getData: () => TemplateEditorData): CompletionSource {
  return (ctx: CompletionContext): CompletionResult | null => {
    const { registry, hints } = getData();
    if (!registry) return null;
    const text = ctx.state.doc.toString();
    const cur = cursorContext(text, ctx.pos);
    if (!cur) return null;
    const options = optionsFor(cur, text, registry, hints);
    if (options.length === 0) return null;
    return {
      from: cur.from,
      options,
      validFor: cur.kind === 'query-value' ? /^[^"'\n]*$/ : /^[A-Za-z0-9_]*$/,
    };
  };
}
