function localYmd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function listDays(sinceIso, nowIso) {
  const d = new Date(sinceIso);
  d.setHours(0, 0, 0, 0);
  const end = new Date(nowIso);
  end.setHours(0, 0, 0, 0);
  const out = [];
  while (d <= end) {
    out.push(localYmd(d));
    d.setDate(d.getDate() + 1);
  }
  return out;
}

export function extractPaths(rows) {
  const seen = new Set();
  for (const row of rows) {
    const p = row?.path;
    if (typeof p === 'string' && p && !p.startsWith('Familiar/')) seen.add(p);
  }
  return [...seen];
}
