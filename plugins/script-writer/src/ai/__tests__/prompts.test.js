import { describe, expect, it } from 'vitest';
import { parse } from '../../fountain/parse.js';
import { ACTIONS, POLISH_PASSES, actionPrompt, askPrompt, outlineText, polishPrompt } from '../prompts.js';

const els = parse('INT. A - DAY\n\n= She arrives.\n\nGo.\n\nEXT. B - NIGHT\n\nRun.');
const sources = [{ n: 1, path: 'p/a.md', title: 'Mara bio', snippet: 's', content: 'Mara is 40.' }, { n: 2, path: 'p/b.md', title: 'Town', snippet: 'Foggy.' }];

describe('prompts', () => {
  it('outlines scenes with synopses', () => {
    expect(outlineText(els)).toBe('1. INT. A - DAY \u2014 She arrives.\n2. EXT. B - NIGHT');
  });
  it('builds an ask prompt with numbered sources, scene, last 6 turns and the question', () => {
    const history = Array.from({ length: 8 }, (_, k) => ({ role: k % 2 ? 'assistant' : 'user', text: `t${k}` }));
    const { system, prompt } = askPrompt({ question: 'How old is Mara?', outline: 'O', scene: 'SCENE', sources, history });
    expect(system).toMatch(/\[n\]/);
    expect(prompt).toContain('[1] Mara bio (p/a.md)\nMara is 40.');
    expect(prompt).toContain('[2] Town (p/b.md)\nFoggy.');
    expect(prompt).toContain('SCENE');
    expect(prompt).not.toContain('t1');
    expect(prompt).toContain('t7');
    expect(prompt.trim().endsWith('How old is Mara?')).toBe(true);
  });
  it('says so when there are no sources', () => {
    expect(askPrompt({ question: 'q', outline: '', scene: '', sources: [], history: [] }).prompt).toContain('(no matching notes found)');
  });
  it('builds action prompts with a schema only for editing actions', () => {
    const rewrite = ACTIONS.find((a) => a.id === 'rewrite');
    const r = actionPrompt({ action: rewrite, direction: 'darker', target: 'TARGET', outline: 'O', sources });
    expect(r.jsonSchema.required).toEqual(['fountain']);
    expect(r.prompt).toContain("Writer's direction: darker");
    expect(r.prompt.trim().endsWith('TARGET')).toBe(true);
    const cont = actionPrompt({ action: ACTIONS.find((a) => a.id === 'continuity'), target: 'T', outline: '', sources });
    expect(cont.jsonSchema).toBeUndefined();
    expect(ACTIONS.map((a) => a.id)).toEqual(['continue', 'rewrite', 'punchup', 'beat', 'continuity']);
  });
  it('builds a polish prompt listing only the chosen passes', () => {
    expect(POLISH_PASSES.filter((p) => p.default).map((p) => p.id)).toEqual(['formatting', 'language']);
    const { prompt, jsonSchema } = polishPrompt({ passes: ['formatting'], sceneText: 'SECTION', characterNames: ['MARA'] });
    expect(prompt).toContain(POLISH_PASSES[0].rule);
    expect(prompt).not.toContain(POLISH_PASSES[1].rule);
    expect(prompt).toContain('MARA');
    expect(jsonSchema.required).toEqual(['fountain']);
  });
  it('throws when no known polish pass ids are selected', () => {
    expect(() => polishPrompt({ passes: [], sceneText: 'TEXT' })).toThrow('Pick at least one polish pass');
    expect(() => polishPrompt({ passes: ['unknown'], sceneText: 'TEXT' })).toThrow('Pick at least one polish pass');
  });
});
