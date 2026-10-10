import { extractPaths, listDays } from './delta.js';
import { renderNoteBlocks, trimToBudget } from './budget.js';
import { buildUserPrompt, SYSTEM_PROMPT } from './prompt.js';
import { parseSweepOutput, SWEEP_JSON_SCHEMA } from './output.js';
import { createNoteIO } from './notes-io.js';
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

export async function runSweep(deps) {
  const { api, settings, state, now, log } = deps;
  // Per-run etag tracking: each rewrite sends the etag of the version read here.
  const { readNoteData, readNote, writeNote } = createNoteIO((...a) => api.fetch(...a));
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
      const data = await readNoteData(p);
      if (data !== null) {
        const modified = data.frontmatter?.updated ?? data.frontmatter?.created ?? '';
        notes.push({ path: p, modified, text: data.body });
      }
    }
    const { kept, dropped } = trimToBudget(notes, settings.budgetChars);
    report.noteCount = kept.length;
    report.droppedCount = dropped.length;

    // 3. current memory + trackers
    const memoryMd = (await readNote(MEMORY_PATH)) ?? '';
    const loopsMd = (await readNote(LOOPS_PATH)) ?? '';
    const decisionsMd = (await readNote(DECISIONS_PATH)) ?? '';

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
        // The backend's claude client defaults to a $0.50/call safety cap;
        // an opus sweep at the full budgetChars deterministically exceeds
        // that, so raise the cap for this call specifically.
        budgetUsd: 5.0,
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
    const freshLoops = parseOpenLoops((await readNote(LOOPS_PATH)) ?? '');
    const mergedLoops = mergeLoops(freshLoops.loops, output.openLoops);
    const freshDecisions = parseDecisions((await readNote(DECISIONS_PATH)) ?? '');
    const mergedDecisions = mergeDecisions(freshDecisions, output.decisions);

    // 6. write-back — briefing first (worst crash outcome: briefing without
    //    tracker update, repaired by the next run)
    const ymd = localYmd(now);
    // A same-day rerun replaces today's briefing; read it for its etag.
    await readNoteData(briefingPath(ymd));
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
    await writeNote(briefingPath(ymd), briefing);
    await writeNote(MEMORY_PATH, output.memoryMarkdown);
    await writeNote(LOOPS_PATH, renderOpenLoops(mergedLoops, freshLoops.unparsed));
    await writeNote(DECISIONS_PATH, renderDecisions(mergedDecisions));

    report.ok = true;
    report.briefingPath = briefingPath(ymd);
    return report;
  } catch (e) {
    report.error = e instanceof Error ? e.message : String(e);
    return report;
  }
}
