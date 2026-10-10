import { describe, expect, it, vi } from 'vitest';
import { EditorState } from '@codemirror/state';
import { PLACEHOLDER_SYNTAX_NOTE, hoverAt, hoverDom } from '../lib/template-editor/hover';
import {
  TEMPLATE_LINT_DELAY_MS,
  templateLintSource,
  toCmDiagnostics,
} from '../lib/template-editor/lint';
import { REGISTRY, TEMPLATE } from './helpers/template-registry';

const posOf = (needle: string, offset = 0) => TEMPLATE.indexOf(needle) + offset;

describe('template hover docs', () => {
  it('describes a prompt, a field and a filter inside placeholders', () => {
    const prompt = hoverAt(TEMPLATE, posOf('{{person.link}}', 3), REGISTRY)!;
    expect(prompt.title).toBe('person — prompt (person)');
    expect(prompt.info).toBe(`A person.\n\nExample: type: person\n\n${PLACEHOLDER_SYNTAX_NOTE}`);
    expect(TEMPLATE.slice(prompt.from, prompt.to)).toBe('person');

    const field = hoverAt(TEMPLATE, posOf('{{person.link}}', 10), REGISTRY)!;
    expect(field.title).toBe('person.link: text');
    expect(field.info).toContain('A wikilink to the person.');

    const filter = hoverAt(TEMPLATE, posOf('format: YYYY', 2), REGISTRY)!;
    expect(filter.title).toBe('| format');
    const variable = hoverAt(TEMPLATE, posOf('{{date |', 3), REGISTRY)!;
    expect(variable.title).toBe('date: date');
  });

  it('describes prompt types and query keys', () => {
    expect(hoverAt(TEMPLATE, posOf('type: person', 8), REGISTRY)!.title).toBe('type: person');
    expect(hoverAt(TEMPLATE, posOf('status: open', 2), REGISTRY)!.title).toBe('status:');
  });

  it('adds the placeholder syntax note to placeholder hovers only', () => {
    expect(PLACEHOLDER_SYNTAX_NOTE).toContain('{{{x}}');
    for (const pos of [
      posOf('{{person.link}}', 3),
      posOf('{{person.link}}', 10),
      posOf('format: YYYY', 2),
      posOf('{{date |', 3),
    ]) {
      expect(hoverDom(hoverAt(TEMPLATE, pos, REGISTRY)!).textContent).toContain(
        PLACEHOLDER_SYNTAX_NOTE,
      );
    }
    const typeHover = hoverDom(hoverAt(TEMPLATE, posOf('type: person', 8), REGISTRY)!);
    expect(typeHover.textContent).not.toContain(PLACEHOLDER_SYNTAX_NOTE);
    const keyHover = hoverDom(hoverAt(TEMPLATE, posOf('status: open', 2), REGISTRY)!);
    expect(keyHover.textContent).not.toContain(PLACEHOLDER_SYNTAX_NOTE);
  });

  it('falls back for a prompt whose type the registry does not list', () => {
    const src = TEMPLATE.replace('type: person', 'type: mystery');
    const h = hoverAt(src, src.indexOf('{{person.link}}') + 3, REGISTRY)!;
    expect(h.title).toBe('person — prompt (mystery)');
    expect(h.info).toContain('A prompt of this template.');
    expect(hoverAt(src, src.indexOf('{{person.link}}') + 10, REGISTRY)).toBeNull();
    expect(hoverAt(src, src.indexOf('type: mystery') + 8, REGISTRY)).toBeNull();
  });

  it('says nothing for unknown names, filter arguments, values and plain text', () => {
    const src = TEMPLATE.replace('{{person.link}}', '{{nobody}}');
    expect(hoverAt(src, src.indexOf('{{nobody}}') + 3, REGISTRY)).toBeNull();
    expect(hoverAt(TEMPLATE, posOf('YYYY-MM-DD', 1), REGISTRY)).toBeNull();
    expect(hoverAt(TEMPLATE, posOf('status: open', 9), REGISTRY)).toBeNull();
    expect(hoverAt(TEMPLATE, posOf('# 1-1 with', 3), REGISTRY)).toBeNull();
    expect(hoverAt(TEMPLATE, posOf('type: meeting', 1), REGISTRY)).toBeNull();
  });

  it('renders hover text without interpreting markup', () => {
    const dom = hoverDom({
      from: 0,
      to: 1,
      title: '<b>x</b>',
      info: '<img src=x onerror=alert(1)>',
    });
    expect(dom.querySelector('img')).toBeNull();
    expect(dom.textContent).toContain('<img src=x onerror=alert(1)>');
  });
});

describe('template lint mapping', () => {
  const doc = EditorState.create({ doc: TEMPLATE }).doc;

  it('debounces at 500 ms', () => {
    expect(TEMPLATE_LINT_DELAY_MS).toBe(500);
  });

  it('maps a placeholder diagnostic onto the whole placeholder', () => {
    const line = TEMPLATE.split('\n').indexOf('# 1-1 with {{person.link}}') + 1;
    const [d] = toCmDiagnostics(doc, [
      { line, col: 12, severity: 'warning', message: 'unknown', code: 'unknown-name' },
    ]);
    expect(doc.sliceString(d!.from, d!.to)).toBe('{{person.link}}');
    expect(d).toMatchObject({ severity: 'warning', message: 'unknown', source: 'template' });
  });

  it('maps other diagnostics onto the word and clamps out-of-range positions', () => {
    const [word, past] = toCmDiagnostics(doc, [
      { line: 3, col: 3, severity: 'error', message: 'bad', code: 'schema' },
      { line: 999, col: 999, severity: 'info', message: 'end', code: 'x' },
    ]);
    expect(doc.sliceString(word!.from, word!.to)).toBe('name');
    expect(past!.from).toBe(doc.length);
    expect(past!.to).toBe(doc.length);
  });

  it('lints the current document and shows nothing when the request fails', async () => {
    const state = EditorState.create({ doc: TEMPLATE });
    const ok = vi
      .fn()
      .mockResolvedValue([{ line: 1, col: 1, severity: 'error', message: 'x', code: 'y' }]);
    expect(await templateLintSource(ok)({ state })).toHaveLength(1);
    expect(ok).toHaveBeenCalledWith(TEMPLATE);
    const failing = vi.fn().mockRejectedValue(new Error('sidecar down'));
    expect(await templateLintSource(failing)({ state })).toEqual([]);
  });
});
