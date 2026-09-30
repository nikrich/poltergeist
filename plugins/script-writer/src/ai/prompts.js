// Prompt builders. Pure: every input is passed in; nothing reads app state.
import { scenes } from '../fountain/outline.js';

const SYSTEM_BASE = 'You are an experienced screenwriting collaborator working on a feature screenplay written in Fountain markup.';

export const FOUNTAIN_RULES = [
  'Write valid Fountain: scene headings start with INT. or EXT. and are uppercase;',
  'character cues are uppercase on their own line with dialogue directly beneath;',
  'parentheticals are in (brackets) on their own line; one blank line between elements;',
  'no markdown, no code fences, no commentary inside the screenplay text.',
].join(' ');

export function outlineText(elements) {
  return scenes(elements).slice(0, 200)
    .map((s) => `${s.number}. ${s.heading}${s.synopsis ? ` \u2014 ${s.synopsis}` : ''}`).join('\n');
}

export function sourcesText(sources) {
  return sources.map((s) => `[${s.n}] ${s.title} (${s.path})\n${s.content ?? s.snippet ?? ''}`).join('\n\n---\n\n');
}

export function askPrompt({ question, outline, scene, sources, history = [] }) {
  const system = `${SYSTEM_BASE} Answer the writer's question using the numbered notes from their vault. `
    + 'Cite notes inline as [n]. If the notes do not cover the question, say so plainly, then offer your own suggestion. '
    + 'Answer in concise markdown.';
  const turns = history.slice(-6).map((t) => `${t.role === 'user' ? 'Writer' : 'You'}: ${t.text}`).join('\n\n');
  const prompt = [
    `## Script outline\n${outline || '(no scenes yet)'}`,
    `## Current scene\n${scene || '(none)'}`,
    `## Notes from the vault\n${sources.length ? sourcesText(sources) : '(no matching notes found)'}`,
    turns ? `## Conversation so far\n${turns}` : '',
    `## Question\n${question}`,
  ].filter(Boolean).join('\n\n');
  return { system, prompt };
}

export const EDIT_SCHEMA = Object.freeze({
  type: 'object',
  properties: { fountain: { type: 'string' }, notes: { type: 'string' } },
  required: ['fountain'],
});

export const REWRITE_PRESETS = ['Tighter', 'Funnier', 'Darker', 'More subtext'];

export const ACTIONS = [
  { id: 'continue', label: 'Continue scene', edits: 'insert', instruction: 'Continue the scene from where the target text ends. Write only the next beats (roughly 5 to 25 lines of Fountain). Do not repeat the target text.' },
  { id: 'rewrite', label: 'Rewrite\u2026', edits: 'replace', needsDirection: true, instruction: "Rewrite the target text following the writer's direction. Keep the story events and characters unless the direction says otherwise." },
  { id: 'punchup', label: 'Punch up dialogue', edits: 'replace', instruction: 'Sharpen only the dialogue in the target text: voice, rhythm, subtext. Keep scene headings, action lines and character cues exactly as they are.' },
  { id: 'beat', label: 'Scene from beat', edits: 'replace', instruction: 'The target text is a beat or synopsis. Write it as a complete scene in Fountain, starting with a scene heading.' },
  { id: 'continuity', label: 'Continuity check', edits: 'none', instruction: 'Check the target text against the notes for contradictions: names, ages, relationships, timeline, locations and established facts. List each issue with a citation [n] and a suggested fix. If there are none, say so.' },
];

export function actionPrompt({ action, direction = '', target, outline, sources }) {
  const system = action.edits === 'none'
    ? `${SYSTEM_BASE} Cite notes inline as [n]. Answer in concise markdown.`
    : `${SYSTEM_BASE} ${FOUNTAIN_RULES} Put the screenplay text in "fountain" and any brief remarks for the writer in "notes".`;
  const prompt = [
    `## Script outline\n${outline || '(no scenes yet)'}`,
    `## Notes from the vault\n${sources.length ? sourcesText(sources) : '(no matching notes found)'}`,
    `## Task\n${action.instruction}${direction ? `\nWriter's direction: ${direction}` : ''}`,
    `## Target text\n${target}`,
  ].join('\n\n');
  return action.edits === 'none' ? { system, prompt } : { system, prompt, jsonSchema: EDIT_SCHEMA };
}

export const POLISH_SCHEMA = Object.freeze({
  type: 'object',
  properties: { fountain: { type: 'string' }, changes: { type: 'string' } },
  required: ['fountain'],
});

export const POLISH_PASSES = [
  { id: 'formatting', label: 'Formatting', default: true, rule: "Fix Fountain formatting so it is industry-correct: uppercase scene headings and character cues, exactly one blank line between elements, dialogue directly under its cue, parentheticals in brackets on their own line, consistent character names and extensions such as (V.O.), (O.S.) and (CONT'D). Do not change any words." },
  { id: 'language', label: 'Language', default: true, rule: "Fix spelling, grammar and punctuation in action and dialogue. Keep the writer's voice, slang and intentional fragments." },
  { id: 'tighten', label: 'Tighten prose', default: false, rule: 'Tighten action lines: cut filler and redundant description and prefer active verbs, keeping every story beat. Do not change dialogue.' },
  { id: 'dialogue', label: 'Punch up dialogue', default: false, rule: 'Punch up dialogue: sharper voice, rhythm and subtext for each character, keeping what happens in the scene.' },
];

export function polishPrompt({ passes, sceneText, characterNames = [] }) {
  const selectedPasses = POLISH_PASSES.filter((p) => passes.includes(p.id));
  if (!selectedPasses.length) throw Error('Pick at least one polish pass');
  const rules = selectedPasses.map((p, i) => `${i + 1}. ${p.rule}`).join('\n');
  const system = `${SYSTEM_BASE} ${FOUNTAIN_RULES} You are polishing one section of a longer script. `
    + 'Return the whole section, polished, in "fountain", and a one-line summary of what you changed in "changes".';
  const prompt = [
    `## Passes\n${rules}\nApply ONLY these passes. Everything they do not cover must stay exactly as written.`,
    `## Known characters\n${characterNames.join(', ') || '(none)'}`,
    `## Section\n${sceneText}`,
  ].join('\n\n');
  return { system, prompt, jsonSchema: POLISH_SCHEMA };
}
