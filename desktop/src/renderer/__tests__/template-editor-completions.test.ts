import { describe, expect, it } from 'vitest';
import { CompletionContext, type CompletionResult } from '@codemirror/autocomplete';
import { EditorState } from '@codemirror/state';
import {
  EMPTY_HINTS,
  templateCompletions,
  valueTypeOf,
  type TemplateEditorData,
} from '../lib/template-editor/completions';
import { REGISTRY, TEMPLATE } from './helpers/template-registry';

const HINTS = { types: ['action_item', 'decision'], statuses: ['done', 'open'], contexts: ['work'] };

function complete(marked: string, data: Partial<TemplateEditorData> = {}): CompletionResult | null {
  const pos = marked.indexOf('‸');
  const doc = marked.replace('‸', '');
  const state = EditorState.create({ doc, selection: { anchor: pos } });
  const source = templateCompletions(() => ({ registry: REGISTRY, hints: HINTS, ...data }));
  return source(new CompletionContext(state, pos, false)) as CompletionResult | null;
}

const labels = (r: CompletionResult | null) => r?.options.map((o) => o.label) ?? [];
const BODY = TEMPLATE.replace('# 1-1 with {{person.link}}', '# {{‸');

describe('template completions', () => {
  it('offers the template prompts first, then registry variables, each with docs', () => {
    const r = complete(BODY);
    expect(labels(r)).toEqual(['person', 'focus', 'date', 'now', 'context', 'title']);
    expect(r!.from).toBe(BODY.indexOf('‸'));
    expect(r!.options[0]).toMatchObject({ detail: 'prompt · person', boost: 2 });
    expect(r!.options[0]!.info).toContain('A person.');
    expect(r!.options[2]!.info).toBe('Today, or the date prompt.\n\nExample: {{date | format: D MMM YYYY}}');
  });

  it('offers the fields of the value type after a dot', () => {
    expect(labels(complete(TEMPLATE.replace('{{person.link}}', '{{person.‸')))).toEqual(['name', 'link']);
    expect(labels(complete(TEMPLATE.replace('{{person.link}}', '{{now.date.‸')))).toEqual(['iso']);
    expect(complete(TEMPLATE.replace('{{person.link}}', '{{focus.‸'))).toBeNull();
  });

  it('offers filters after a pipe, with ": " for those that need an argument', () => {
    const r = complete(TEMPLATE.replace('{{person.link}}', '{{date | ‸'));
    expect(labels(r)).toEqual(['format', 'upper']);
    expect(r!.options[0]!.apply).toBe('format: ');
    expect(r!.options[1]!.apply).toBe('upper');
  });

  it('offers prompt types on a prompt type line', () => {
    const r = complete(TEMPLATE.replace('      type: person', '      type: ‸'));
    expect(labels(r)).toEqual(['text', 'person', 'date']);
  });

  it('offers query keys and their known values inside a query fence', () => {
    const keys = complete(TEMPLATE.replace('status: open', '‸'));
    expect(labels(keys)).toEqual(['type', 'status', 'sort', 'context']);
    expect(keys!.options[0]!.apply).toBe('type: ');
    expect(labels(complete(TEMPLATE.replace('status: open', 'status: ‸')))).toEqual(['open', 'done']);
    expect(labels(complete(TEMPLATE.replace('status: open', 'type: ‸')))).toEqual(['action_item', 'decision']);
    expect(labels(complete(TEMPLATE.replace('status: open', 'context: ‸')))).toEqual(['work']);
    expect(labels(complete(TEMPLATE.replace('status: open', 'sort: ‸')))).toEqual([
      'created desc',
      'created asc',
      'updated desc',
      'updated asc',
    ]);
    const value = complete(TEMPLATE.replace('status: open', 'status: ‸'));
    expect(value!.options[0]!.info).toBe('open = not done.\n\nExample: status: open');
  });

  it('skips query completions when the registry has no query keys (C2 absent)', () => {
    const { queryKeys: _omit, ...withoutQueries } = REGISTRY;
    expect(complete(TEMPLATE.replace('status: open', '‸'), { registry: withoutQueries })).toBeNull();
    expect(complete(TEMPLATE.replace('status: open', 'status: ‸'), { registry: withoutQueries })).toBeNull();
    expect(labels(complete(BODY, { registry: withoutQueries }))).toContain('person');
  });

  it('returns nothing before the registry loads or outside any context', () => {
    expect(complete(BODY, { registry: null })).toBeNull();
    expect(complete('plain ‸text', { hints: EMPTY_HINTS })).toBeNull();
  });

  it('resolves value types through prompts, variables and fields', () => {
    const prompts = [{ id: 'who', type: 'person' }];
    expect(valueTypeOf(['who'], prompts, REGISTRY)).toBe('person');
    expect(valueTypeOf(['now', 'date'], prompts, REGISTRY)).toBe('date');
    expect(valueTypeOf(['nope'], prompts, REGISTRY)).toBeNull();
    expect(valueTypeOf(['who', 'nope', 'iso'], prompts, REGISTRY)).toBeNull();
  });

  it('treats a prompt type the registry does not list as unknown', () => {
    expect(valueTypeOf(['pick'], [{ id: 'pick', type: 'colour' }], REGISTRY)).toBeNull();
    const doc = TEMPLATE.replace('      type: person', '      type: colour');
    expect(complete(doc.replace('{{person.link}}', '{{person.‸'))).toBeNull();
    expect(complete(doc.replace('# 1-1 with {{person.link}}', '# {{‸'))!.options[0]).toMatchObject({
      label: 'person',
      detail: 'prompt · colour',
    });
  });
});
