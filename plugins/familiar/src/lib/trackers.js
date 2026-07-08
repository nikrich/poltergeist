// Tracker notes are plain markdown, one machine-parseable line per item.
// The vault is the database: humans may edit these files; any list line that
// doesn't parse is preserved under "## Unparsed" rather than dropped.

const LOOP_RE = new RegExp(
  '^- \\[( |x)\\] <!--id:([a-z0-9-]+)--> (.+?)' +
  '(?: — owed to (.+?))?' +
  ' \\(from \\[source\\]\\((.+?)\\), first seen (\\d{4}-\\d{2}-\\d{2})\\)' +
  '(?: \\{(stale|dismissed)\\})?$',
);

export function parseOpenLoops(md) {
  const loops = [];
  const unparsed = [];
  for (const line of md.split('\n')) {
    if (!line.startsWith('- ')) continue;
    const m = LOOP_RE.exec(line);
    if (!m) {
      unparsed.push(line);
      continue;
    }
    const [, box, id, text, owedTo, sourcePath, firstSeen, tag] = m;
    loops.push({
      id, text, owedTo: owedTo ?? null, sourcePath, firstSeen,
      status: box === 'x' ? 'done' : (tag ?? 'open'),
    });
  }
  return { loops, unparsed };
}

function renderLoop(l) {
  const box = l.status === 'done' ? 'x' : ' ';
  const owed = l.owedTo ? ` — owed to ${l.owedTo}` : '';
  const tag = l.status === 'stale' || l.status === 'dismissed' ? ` {${l.status}}` : '';
  return `- [${box}] <!--id:${l.id}--> ${l.text}${owed} (from [source](${l.sourcePath}), first seen ${l.firstSeen})${tag}`;
}

export function renderOpenLoops(loops, unparsed) {
  const lines = ['# Open loops', '', ...loops.map(renderLoop)];
  if (unparsed.length) lines.push('', '## Unparsed', '', ...unparsed);
  return lines.join('\n') + '\n';
}

export function mergeLoops(current, fromModel) {
  const byId = new Map(current.map((l) => [l.id, l]));
  const seen = new Set();
  const out = [];
  for (const cur of current) {
    seen.add(cur.id);
    const m = fromModel.find((x) => x.id === cur.id);
    if (!m || cur.status === 'done' || cur.status === 'dismissed') {
      out.push(cur); // user state wins; model omission never loses a loop
      continue;
    }
    const status = m.status === 'dismissed' ? cur.status : m.status;
    out.push({ ...cur, status });
  }
  for (const m of fromModel) {
    if (byId.has(m.id)) continue;
    out.push({ ...m, owedTo: m.owedTo ?? null, status: m.status === 'dismissed' ? 'open' : m.status });
  }
  return out;
}

const DECISION_RE = /^- (\d{4}-\d{2}-\d{2}) — (.+?) \(from \[source\]\((.+?)\)\)$/;

export function parseDecisions(md) {
  const out = [];
  for (const line of md.split('\n')) {
    const m = DECISION_RE.exec(line);
    if (m) out.push({ date: m[1], text: m[2], sourcePath: m[3] });
  }
  return out;
}

export function renderDecisions(list) {
  return ['# Decisions', '', ...list.map((d) => `- ${d.date} — ${d.text} (from [source](${d.sourcePath}))`)].join('\n') + '\n';
}

export function mergeDecisions(current, fromModel) {
  const key = (d) => `${d.date}${d.text}`;
  const seen = new Set(current.map(key));
  const out = [...current];
  for (const d of fromModel) {
    if (!seen.has(key(d))) {
      seen.add(key(d));
      out.push(d);
    }
  }
  return out;
}
