import type { ArtefactKind, ArtefactSummary } from '../../../shared/design-types';

export const KIND_ICON: Record<ArtefactKind, string> = {
  prototype: 'app-window',
  worktree: 'git-branch',
  board: 'workflow',
};

export const KIND_LABEL: Record<ArtefactKind, string> = {
  prototype: 'prototype',
  worktree: 'worktree',
  board: 'board',
};

/** The revision that matters for the artefact's kind. */
export function latestRev(a: ArtefactSummary): number {
  return a.kind === 'board' ? a.board_rev : a.ui_rev;
}

/** Local YYYY-MM-DD, `offsetDays` from today. */
export function localDay(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function dayLabel(date: string): string {
  if (date === localDay(0)) return 'Today';
  if (date === localDay(-1)) return 'Yesterday';
  return date;
}

/** Consecutive runs of the same date, in list order (the API sorts newest first). */
export function groupByDay(items: ArtefactSummary[]): { day: string; items: ArtefactSummary[] }[] {
  const groups: { day: string; items: ArtefactSummary[] }[] = [];
  for (const a of items) {
    const last = groups[groups.length - 1];
    if (last && last.day === a.date) last.items.push(a);
    else groups.push({ day: a.date, items: [a] });
  }
  return groups;
}
