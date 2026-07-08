import { extractPaths, listDays } from './delta.js';
import { renderNoteBlocks, trimToBudget } from './budget.js';
import { buildUserPrompt, SYSTEM_PROMPT } from './prompt.js';
import { parseSweepOutput, SWEEP_JSON_SCHEMA } from './output.js';
import {
  mergeDecisions, mergeLoops, parseDecisions, parseOpenLoops,
  renderDecisions, renderOpenLoops,
} from './trackers.js';

export const MEMORY_PATH = 'Familiar/memory.md';
export const LOOPS_PATH = 'Familiar/open-loops.md';
export const DECISIONS_PATH = 'Familiar/decisions.md';
export const briefingPath = (ymd) => `Familiar/briefings/${ymd}.md`;

function localYmd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

async function getJson(api, path) {
  const r = await api.fetch('GET', path);
  if (!r.ok) throw new Error(`GET ${path}: ${r.error}`);
  return r.data;
}

/** Read a note; missing note (404) → null, other failures throw. */
async function readNoteData(api, notePath) {
  const r = await api.fetch('GET', `/v1/notes?path=${encodeURIComponent(notePath)}`);
  if (r.ok) return r.data;
  if (r.status === 404) return null;
  throw new Error(`read ${notePath}: ${r.error}`);
}

/** Read a note body; missing note (404) → null, other failures throw. */
async function readNote(api, notePath) {
  const data = await readNoteData(api, notePath);
  return data ? data.body : null;
}

async function writeNote(api, notePath, content) {
  const r = await api.fetch('PUT', '/v1/notes', { path: notePath, content });
  if (!r.ok) throw new Error(`write ${notePath}: ${r.error}`);
}

export async function runSweep(deps) {
  const { api, settings, state, now, log } = deps;
  const windowStart = state.lastSuccessfulRunAt
    ?? new Date(now.getTime() - 7 * 24 * 3600 * 1000).toISOString();
  const windowEnd = now.toISOString();
  const report = {
    ok: false, windowStart, windowEnd, noteCount: 0, droppedCount: 0, costUsd: null,
  };

  try {
    // 1. delta paths from the activity feed, one call per day in the window
    const pathSet = [];
    for (const day of listDays(windowStart, windowEnd)) {
      const rows = await getJson(api, `/v1/activity?date=${day}&windowMinutes=1440`);
      pathSet.push(...rows);
    }
    const paths = extractPaths(pathSet);

    // 2. full text of every delta note (dropped from the feed if unreadable)
    const notes = [];
    for (const p of paths) {
      const data = await readNoteData(api, p);
      if (data !== null) {
        const modified = data.frontmatter?.updated ?? data.frontmatter?.created ?? '';
        notes.push({ path: p, modified, text: data.body });
      }
    }
    const { kept, dropped } = trimToBudget(notes, settings.budgetChars);
    report.noteCount = kept.length;
    report.droppedCount = dropped.length;

    // 3. current memory + trackers
    const memoryMd = (await readNote(api, MEMORY_PATH)) ?? '';
    const loopsMd = (await readNote(api, LOOPS_PATH)) ?? '';
    const decisionsMd = (await readNote(api, DECISIONS_PATH)) ?? '';

    // 4. LLM call, one retry on contract violation
    const userPrompt = buildUserPrompt({
      memoryMd, openLoopsMd: loopsMd, decisionsMd,
      noteBlocks: renderNoteBlocks(kept), droppedPaths: dropped,
      windowStart, windowEnd,
    });
    let output = null;
    let lastErr = null;
    let lastRawText = '';
    for (let attempt = 0; attempt < 2 && !output; attempt++) {
      const prompt = lastErr
        ? `${userPrompt}\n\nYour previous output was rejected: ${lastErr}. Return ONLY the JSON object.`
        : userPrompt;
      const r = await api.fetch('POST', '/v1/llm/run', {
        prompt, system: SYSTEM_PROMPT, model: settings.model,
        jsonSchema: SWEEP_JSON_SCHEMA, timeoutSeconds: 840,
      });
      if (!r.ok) throw new Error(`llm/run transport: ${r.error}`);
      if (r.data.error) throw new Error(`llm/run: ${r.data.error}`);
      report.costUsd = (report.costUsd ?? 0) + (r.data.costUsd ?? 0);
      lastRawText = r.data.text ?? '';
      try {
        output = parseSweepOutput(r.data);
      } catch (e) {
        lastErr = e.message;
        log(`sweep output rejected (attempt ${attempt + 1}): ${e.message}`);
      }
    }
    if (!output) {
      report.rawOutput = lastRawText; // main.js persists this to dataDir for debugging
      throw new Error(`output contract violated twice: ${lastErr}`);
    }

    // 5. merge trackers against a FRESH read (user may have edited mid-run)
    const freshLoops = parseOpenLoops((await readNote(api, LOOPS_PATH)) ?? '');
    const mergedLoops = mergeLoops(freshLoops.loops, output.openLoops);
    const freshDecisions = parseDecisions((await readNote(api, DECISIONS_PATH)) ?? '');
    const mergedDecisions = mergeDecisions(freshDecisions, output.decisions);

    // 6. write-back — briefing first (worst crash outcome: briefing without
    //    tracker update, repaired by the next run)
    const ymd = localYmd(now);
    const briefing = [
      '---',
      'type: familiar-briefing',
      `window: ${windowStart}..${windowEnd}`,
      `notes: ${kept.length}`,
      `dropped: ${dropped.length}`,
      `created: ${windowEnd}`,
      '---',
      '',
      output.briefingMarkdown,
    ].join('\n');
    await writeNote(api, briefingPath(ymd), briefing);
    await writeNote(api, MEMORY_PATH, output.memoryMarkdown);
    await writeNote(api, LOOPS_PATH, renderOpenLoops(mergedLoops, freshLoops.unparsed));
    await writeNote(api, DECISIONS_PATH, renderDecisions(mergedDecisions));

    report.ok = true;
    report.briefingPath = briefingPath(ymd);
    return report;
  } catch (e) {
    report.error = e instanceof Error ? e.message : String(e);
    return report;
  }
}
