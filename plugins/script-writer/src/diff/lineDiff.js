// LCS diffs for reviewing AI edits. Scenes are small; the cap keeps a
// pathological input from allocating a huge table.
const MAX_CELLS = 4_000_000;

function lcsOps(a, b) {
  const n = a.length;
  const m = b.length;
  if (n * m > MAX_CELLS) return [...a.map((t) => ({ type: 'del', text: t })), ...b.map((t) => ({ type: 'add', text: t }))];
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  }
  const ops = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { ops.push({ type: 'equal', text: a[i] }); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) ops.push({ type: 'del', text: a[i++] });
    else ops.push({ type: 'add', text: b[j++] });
  }
  while (i < n) ops.push({ type: 'del', text: a[i++] });
  while (j < m) ops.push({ type: 'add', text: b[j++] });
  return ops;
}

export const diffLines = (a, b) => lcsOps(a, b);

export function hunks(a, b) {
  const out = [];
  for (const op of lcsOps(a, b)) {
    const last = out[out.length - 1];
    if (op.type === 'equal') {
      if (last?.type === 'equal') last.lines.push(op.text); else out.push({ type: 'equal', lines: [op.text] });
    } else {
      if (last?.type !== 'change') out.push({ type: 'change', del: [], add: [] });
      out[out.length - 1][op.type].push(op.text);
    }
  }
  return out;
}

export function applyHunks(hs, accept) {
  const lines = [];
  let c = 0;
  for (const h of hs) {
    if (h.type === 'equal') lines.push(...h.lines);
    else lines.push(...(accept(c++) ? h.add : h.del));
  }
  return lines;
}

export function wordDiff(x, y) {
  const tok = (s) => s.split(/(\s+)/).filter((t) => t !== '');
  const merged = [];
  for (const op of lcsOps(tok(x), tok(y))) {
    const last = merged[merged.length - 1];
    if (last?.type === op.type) last.text += op.text; else merged.push({ ...op });
  }
  return merged;
}
