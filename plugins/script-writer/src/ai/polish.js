// Whole-document polish, run per section so long scripts fit and one bad
// section never sinks the rest. Review/compose happens on line hunks.
import { applyHunks, hunks } from '../diff/lineDiff.js';
import { characters, joinBlocks, sceneBlocks } from '../fountain/outline.js';
import { parse } from '../fountain/parse.js';
import { BUDGETS, runLlm } from './llm.js';
import { polishPrompt } from './prompts.js';
import { checkFountain } from './validate.js';

export const POLISH_CONCURRENCY = 3;

export function polishUnits(text) {
  const sb = sceneBlocks(text);
  const units = [];
  if (sb.pre.trim()) units.push({ kind: 'pre', index: -1, heading: 'Opening', text: sb.pre });
  sb.blocks.forEach((b, i) => units.push({ kind: 'scene', index: i, heading: b.text.split('\n')[0].trim(), text: b.text }));
  return { sb, units };
}

/** text must be the script BODY only; the title page lives in meta and must never be sent. */
export async function polishDocument(plugin, {
  text, passes, budgetPerSection = BUDGETS.polishPerSection, concurrency = POLISH_CONCURRENCY, onProgress = () => {}, signal,
}) {
  if (!passes?.length) throw new Error('Pick at least one polish pass');
  if (signal?.aborted) throw new Error('Polish cancelled');
  const { sb, units } = polishUnits(text);
  const names = characters(parse(text)).map((c) => c.name);
  const results = new Array(units.length);
  let next = 0;
  let done = 0;

  async function worker() {
    while (next < units.length && !signal?.aborted) {
      const k = next++;
      const unit = units[k];
      try {
        const { system, prompt, jsonSchema } = polishPrompt({ passes, sceneText: unit.text, characterNames: names });
        const out = await runLlm(plugin, { system, prompt, jsonSchema, budgetUsd: budgetPerSection });
        const check = checkFountain(unit.text, out.structured?.fountain, { minKeep: 0.6, keepHeading: unit.kind === 'scene', requireStructure: true });
        results[k] = check.ok
          ? { ...unit, polished: check.text, status: check.text === unit.text ? 'unchanged' : 'changed', summary: out.structured?.changes ?? '' }
          : { ...unit, polished: unit.text, status: 'rejected', reason: check.reason };
      } catch (err) {
        results[k] = { ...unit, polished: unit.text, status: 'error', reason: err.message };
      }
      done++;
      try { onProgress({ done, total: units.length }); } catch { /* a UI callback must never sink the run */ }
    }
  }

  await Promise.all(Array.from({ length: Math.max(1, Math.min(concurrency, units.length)) }, worker));
  if (signal?.aborted) throw new Error('Polish cancelled');
  return { sb, results };
}

export function composePolished({ sb, results }, decide) {
  const texts = results.map((r, u) => {
    if (r.status !== 'changed') return r.text;
    return applyHunks(hunks(r.text.split('\n'), r.polished.split('\n')), (c) => decide(u, c)).join('\n');
  });
  const offset = results[0]?.kind === 'pre' ? 1 : 0;
  return joinBlocks({
    ...sb,
    pre: offset ? texts[0] : sb.pre,
    blocks: sb.blocks.map((b, i) => ({ ...b, text: texts[i + offset] })),
  });
}
