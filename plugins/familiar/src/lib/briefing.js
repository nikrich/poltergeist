// Pure helpers for rendering briefing notes in the redesigned screen.

/** Split a briefing's markdown body into a preamble + `## ` sections.
 * Fenced code blocks are respected (a `## ` inside ``` is not a heading). */
export function splitBriefingSections(md) {
  const lines = String(md ?? '').split('\n');
  const sections = [];
  let current = null;
  const preamble = [];
  let inFence = false;
  for (const line of lines) {
    if (/^```/.test(line.trim())) inFence = !inFence;
    const m = !inFence && /^## (.+)$/.exec(line);
    if (m) {
      current = { title: m[1].trim(), body: '' };
      sections.push(current);
      continue;
    }
    if (current) current.body += line + '\n';
    else preamble.push(line);
  }
  for (const s of sections) s.body = s.body.trim();
  return { preamble: preamble.join('\n').trim(), sections };
}

/** Whole days between an ISO date (YYYY-MM-DD) and now; null on garbage. */
export function ageDays(firstSeen, now = new Date()) {
  const t = Date.parse(firstSeen);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.floor((now.getTime() - t) / 86_400_000));
}

const ICONS = [
  [/theme/i, 'target'],
  [/open loop/i, 'repeat'],
  [/decision/i, 'gavel'],
  [/contradiction/i, 'split'],
  [/blind spot/i, 'eye-off'],
];

/** Lucide icon name for a briefing section title. */
export function sectionIcon(title) {
  for (const [rx, icon] of ICONS) if (rx.test(title)) return icon;
  return 'sparkles';
}

/** Successful runs with briefings → history rows, newest first, deduped by
 * path (latest run per briefing wins — it has the freshest stats). */
export function historyFromRuns(runs) {
  const byPath = new Map();
  for (const r of runs ?? []) {
    if (!r?.ok || !r.briefingPath) continue;
    const prev = byPath.get(r.briefingPath);
    if (!prev || String(r.finishedAt) > String(prev.finishedAt)) byPath.set(r.briefingPath, r);
  }
  return [...byPath.values()]
    .sort((a, b) => String(b.finishedAt).localeCompare(String(a.finishedAt)))
    .map((r) => ({
      path: r.briefingPath,
      date: /(\d{4}-\d{2}-\d{2})/.exec(r.briefingPath)?.[1] ?? r.briefingPath,
      finishedAt: r.finishedAt,
      noteCount: r.noteCount ?? null,
      costUsd: r.costUsd ?? null,
    }));
}
