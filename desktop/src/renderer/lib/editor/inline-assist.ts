import type { Editor } from '@tiptap/core';
import type { DocsAssistMode, DocsAssistRequest } from '../../../shared/api-types';
import { rangeMarkdown } from './markdown';

/** Spec: continue sends the text before the cursor, capped at 8k chars. */
export const BEFORE_CAP = 8000;

/** Which note inline AI reads: a jot (jots screen) or any vault note (viewer). */
export type InlineAssistTarget = { jot_id: string } | { path: string };

/** Snapshot taken when the popover opens (⌘J). */
export interface InlineContext {
  from: number;
  to: number;
  empty: boolean;
  /** Markdown of the selection ('' when collapsed). */
  selection: string;
  /** Markdown of [0, to), last BEFORE_CAP chars. */
  before: string;
  /** The character just before `to` ('' at the start; atoms read as ' '). */
  charBefore: string;
}

export interface InlineAction {
  mode: DocsAssistMode;
  instruction?: string;
  targetLanguage?: string;
}

export const QUICK_ACTIONS: ReadonlyArray<{
  mode: 'continue' | 'polish' | 'expand' | 'summarize';
  label: string;
  needsSelection: boolean;
}> = [
  { mode: 'continue', label: 'continue', needsSelection: false },
  { mode: 'polish', label: 'polish', needsSelection: true },
  { mode: 'expand', label: 'expand', needsSelection: true },
  { mode: 'summarize', label: 'summarize', needsSelection: true },
];

export const LANGUAGES: ReadonlyArray<{ name: string; label: string }> = [
  { name: 'English', label: 'english' },
  { name: 'Afrikaans', label: 'afrikaans' },
];

// Source: _LANGUAGE_RE in ghostbrain/api/models/docs.py (the sidecar 422s
// anything else): a letter, then letters, spaces and ()'-, at most 40.
const LANGUAGE_RE = /^\p{L}[\p{L} ()'-]{0,39}$/u;

/** Whether a typed "other…" language passes the sidecar's check. */
export function isLanguageName(value: string): boolean {
  return LANGUAGE_RE.test(value.trim());
}

export function captureInlineContext(editor: Editor): InlineContext {
  const { from, to, empty } = editor.state.selection;
  return {
    from,
    to,
    empty,
    selection: empty ? '' : rangeMarkdown(editor, from, to),
    before: rangeMarkdown(editor, 0, to).slice(-BEFORE_CAP),
    charBefore: to > 0 ? editor.state.doc.textBetween(to - 1, to, '\n', ' ') : '',
  };
}

function insertsAtCursor(action: InlineAction, ctx: InlineContext): boolean {
  return action.mode === 'continue' || ctx.empty;
}

export function buildInlineRequest(
  target: InlineAssistTarget,
  action: InlineAction,
  ctx: InlineContext,
  streamId: string,
): DocsAssistRequest {
  const instruction = action.instruction?.trim();
  const base: DocsAssistRequest = {
    ...target,
    stream_id: streamId,
    mode: action.mode,
    ...(instruction ? { instruction } : {}),
  };
  if (insertsAtCursor(action, ctx)) return { ...base, placement: 'cursor', before: ctx.before };
  return {
    ...base,
    ...(action.mode === 'translate' && action.targetLanguage
      ? { target_language: action.targetLanguage }
      : {}),
    placement: 'selection',
    selection: ctx.selection,
  };
}

export function suggestionRange(action: InlineAction, ctx: InlineContext): { from: number; to: number } {
  return insertsAtCursor(action, ctx) ? { from: ctx.to, to: ctx.to } : { from: ctx.from, to: ctx.to };
}

export function joinWithSpaceFor(action: InlineAction, ctx: InlineContext): boolean {
  return insertsAtCursor(action, ctx) && /\S/.test(ctx.charBefore);
}

const OPEN_MD_FENCE = /^\s*```(?:markdown|md)[ \t]*\r?\n/;
// A fence with nothing inside (any info string, closed or not) — accepting it
// would replace the selection with an empty code block.
const EMPTY_FENCE = /^\s*```[^\s`]*[ \t]*(?:\r?\n\s*```)?\s*$/;

/** Drop a whole-answer ```markdown fence (finished or still streaming) and
 * blank edges. Real fences (mermaid, toc, plain code) are kept; an empty fence
 * is no answer at all. */
export function cleanModelOutput(text: string): string {
  if (EMPTY_FENCE.test(text)) return '';
  let t = text;
  const open = OPEN_MD_FENCE.exec(t);
  if (open) t = t.slice(open[0].length).replace(/\r?\n?```\s*$/, '');
  return t.replace(/^(?:[ \t]*\r?\n)+/, '').replace(/\s+$/, '');
}

export function newStreamId(): string {
  const c = globalThis.crypto as Crypto | undefined;
  const id =
    c && typeof c.randomUUID === 'function'
      ? c.randomUUID()
      : `${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
  return `inline-${id}`;
}
