/**
 * The answers last used to make a note from a template, so the template
 * editor's Test run starts from real values (spec C3: "the most recent real
 * values (last person, today)"). Per template, plus the latest value per
 * prompt id across templates, so a new template's `person` prompt starts
 * from the last person picked anywhere. localStorage only; every failure
 * is silent and just means "no remembered answers".
 */

export const LAST_ANSWERS_KEY = 'gb.templates.lastAnswers.v1';
export const MAX_REMEMBERED_TEMPLATES = 50;
export const MAX_REMEMBERED_PROMPTS = 100;
export const MAX_REMEMBERED_CHARS = 500;

interface Stored {
  byTemplate: Record<string, Record<string, string>>;
  byPrompt: Record<string, string>;
}

function load(): Stored {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(LAST_ANSWERS_KEY) ?? 'null');
    if (parsed && typeof parsed === 'object') {
      const p = parsed as Partial<Stored>;
      return {
        byTemplate: p.byTemplate && typeof p.byTemplate === 'object' ? p.byTemplate : {},
        byPrompt: p.byPrompt && typeof p.byPrompt === 'object' ? p.byPrompt : {},
      };
    }
  } catch {
    // unreadable or blocked storage: nothing remembered
  }
  return { byTemplate: {}, byPrompt: {} };
}

/** Keep the newest `max` keys; insertion order is recency (re-set keys move last). */
function trim<T>(record: Record<string, T>, max: number): Record<string, T> {
  const keys = Object.keys(record);
  return Object.fromEntries(keys.slice(Math.max(0, keys.length - max)).map((k) => [k, record[k]!]));
}

export function rememberAnswers(templateId: string, answers: Record<string, string>): void {
  const kept = Object.fromEntries(
    Object.entries(answers).filter(
      ([, v]) => typeof v === 'string' && v.trim() !== '' && v.length <= MAX_REMEMBERED_CHARS,
    ),
  );
  const stored = load();
  delete stored.byTemplate[templateId];
  stored.byTemplate[templateId] = kept;
  for (const [k, v] of Object.entries(kept)) {
    delete stored.byPrompt[k];
    stored.byPrompt[k] = v;
  }
  const next: Stored = {
    byTemplate: trim(stored.byTemplate, MAX_REMEMBERED_TEMPLATES),
    byPrompt: trim(stored.byPrompt, MAX_REMEMBERED_PROMPTS),
  };
  try {
    localStorage.setItem(LAST_ANSWERS_KEY, JSON.stringify(next));
  } catch {
    // full or blocked storage: forget silently
  }
}

/** Starting answers for a Test run: this template's last answers, else the
 * latest answer to a prompt with the same id from any template. */
export function initialAnswers(templateId: string, promptIds: string[]): Record<string, string> {
  const { byTemplate, byPrompt } = load();
  const own = byTemplate[templateId] ?? {};
  const out: Record<string, string> = {};
  for (const id of promptIds) {
    const value = own[id] ?? byPrompt[id];
    if (typeof value === 'string') out[id] = value;
  }
  return out;
}
