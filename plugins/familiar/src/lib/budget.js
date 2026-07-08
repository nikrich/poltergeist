export function trimToBudget(notes, maxChars) {
  const kept = [...notes].sort((a, b) => String(a.modified).localeCompare(String(b.modified)));
  const dropped = [];
  const total = () => kept.reduce((n, x) => n + x.text.length, 0);
  while (kept.length > 1 && total() > maxChars) dropped.push(kept.shift().path);
  return { kept, dropped };
}

export function renderNoteBlocks(notes) {
  return notes
    .map((n) => `<note path="${n.path}" modified="${n.modified ?? ''}">\n${n.text}\n</note>`)
    .join('\n\n');
}
