/** Printed length: emphasis markers (* _) don't print; an escaped \* prints one char. */
export function visibleLength(s) {
  return s.replace(/\\[*_]/g, 'x').replace(/[*_]/g, '').length;
}

export function wrap(text, width) {
  const out = [];
  for (const para of String(text).split('\n')) {
    const words = para.trim() === '' ? [] : para.trim().split(/ +/);
    let line = '';
    for (let w of words) {
      while (visibleLength(w) > width) {
        if (line) { out.push(line); line = ''; }
        out.push(w.slice(0, width));
        w = w.slice(width);
      }
      const candidate = line ? `${line} ${w}` : w;
      if (visibleLength(candidate) <= width) line = candidate;
      else { out.push(line); line = w; }
    }
    out.push(line);
  }
  return out;
}
