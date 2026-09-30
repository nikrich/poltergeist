import { StateField } from '@codemirror/state';
import { parse } from '../fountain/parse.js';

export function analyze(text) {
  const elements = parse(text);
  const lineTypes = [];
  for (const el of elements) for (let l = el.line; l <= el.lineEnd; l++) lineTypes[l] = el.type;
  return { elements, lineTypes };
}

/** Whole-document parse, recomputed on every doc change (10k lines < 200ms). */
export const analysisField = StateField.define({
  create: (state) => analyze(state.doc.toString()),
  update: (value, tr) => (tr.docChanged ? analyze(tr.newDoc.toString()) : value),
});
