// Tracker notes are plain markdown, one machine-parseable line per item.
// The vault is the database: humans may edit these files; any list line that
// doesn't parse is preserved under "## Unparsed" rather than dropped.

// The " — owed to " separator and the "(from [source](" trailer are the only
// structural delimiters in a loop line; free-form text/owedTo could otherwise
// contain either substring and be mis-split. The suffix "(from [source](…),
// first seen YYYY-MM-DD)[ {tag}]" is anchored to the END of the line with a
// GREEDY head, so the regex engine backtracks from the right and the LAST
// occurrence of that suffix shape (i.e. the real, trailing one) always wins,
// even if the free text happens to contain a look-alike substring earlier on.
const OWED_SEP = ' — owed to ';

const LOOP_RE = new RegExp(
  '^- \\[( |x)\\] <!--id:([a-z0-9-]+)--> (.+) \\(from \\[source\\]\\((.+)\\), first seen (\\d{4}-\\d{2}-\\d{2})\\)' +
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
    const [, box, id, head, sourcePath, firstSeen, tag] = m;
    // owedTo has no end anchor of its own, so split the head on the LAST
    // occurrence of the separator: render-time sanitization (see
    // sanitizeField) guarantees free text can never contain this literal
    // substring, so any occurrence found here is the real separator.
    const sepIdx = head.lastIndexOf(OWED_SEP);
    const text = sepIdx === -1 ? head : head.slice(0, sepIdx);
    const owedTo = sepIdx === -1 ? null : head.slice(sepIdx + OWED_SEP.length);
    loops.push({
      id, text, owedTo, sourcePath, firstSeen,
      status: box === 'x' ? 'done' : (tag ?? 'open'),
    });
  }
  return { loops, unparsed };
}

// Free-text fields (loop text/owedTo, decision text) must never contain the
// literal delimiters the line format uses to locate field boundaries, or a
// parse(render(x)) round-trip could split a field in the wrong place. Swap
// the em dash for a hyphen and split up the source-link delimiter so these
// substrings can never be mistaken for the real separators (round-trip safety).
function sanitizeField(s) {
  if (s == null) return s;
  return s
    .replace(/ — owed to /g, ' - owed to ')
    .replace(/\(from \[source\]\(/g, '(from [source] (')
    // Tracker notes are one machine-parseable line per item; an embedded
    // newline in model- or user-supplied text would otherwise split the
    // entry across lines and corrupt the file (unparseable, or parsed as a
    // truncated entry plus a stray "unparsed" line).
    .replace(/\s*\n\s*/g, ' ');
}

function renderLoop(l) {
  const box = l.status === 'done' ? 'x' : ' ';
  const text = sanitizeField(l.text);
  const owedTo = l.owedTo ? sanitizeField(l.owedTo) : null;
  const owed = owedTo ? `${OWED_SEP}${owedTo}` : '';
  const tag = l.status === 'stale' || l.status === 'dismissed' ? ` {${l.status}}` : '';
  return `- [${box}] <!--id:${l.id}--> ${text}${owed} (from [source](${l.sourcePath}), first seen ${l.firstSeen})${tag}`;
}

export function renderOpenLoops(loops, unparsed) {
  const lines = ['# Open loops', '', ...loops.map(renderLoop)];
  if (unparsed.length) lines.push('', '## Unparsed', '', ...unparsed);
  return lines.join('\n') + '\n';
}

export function mergeLoops(current, fromModel) {
  const byId = new Map(current.map((l) => [l.id, l]));
  const out = [];
  for (const cur of current) {
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

// Same end-anchoring strategy as LOOP_RE: greedy text capture backtracks from
// the right, so the LAST "(from [source](…))" wins even if free text contains
// a look-alike substring.
const DECISION_RE = /^- (\d{4}-\d{2}-\d{2}) — (.+) \(from \[source\]\((.+)\)\)$/;

export function parseDecisions(md) {
  const out = [];
  for (const line of md.split('\n')) {
    const m = DECISION_RE.exec(line);
    if (m) out.push({ date: m[1], text: m[2], sourcePath: m[3] });
  }
  return out;
}

export function renderDecisions(list) {
  return ['# Decisions', '', ...list.map((d) => `- ${d.date} — ${sanitizeField(d.text)} (from [source](${d.sourcePath}))`)].join('\n') + '\n';
}

export function mergeDecisions(current, fromModel) {
  // `current` was read back through parseDecisions, so its text is already
  // sanitized (renderDecisions sanitizes before writing). `fromModel` is raw
  // LLM output — sanitize its text before computing the dedup key (the same
  // transform renderDecisions applies at write time), or a delimiter-bearing
  // decision the model re-emits every run would never match its own
  // previously-written (sanitized) copy and would duplicate on every sweep.
  const key = (d) => `${d.date}${sanitizeField(d.text)}`;
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
