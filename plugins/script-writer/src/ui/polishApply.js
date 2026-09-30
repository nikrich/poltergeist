// Decides what applying a polish result should do, given the live document.
export function planPolishApply({ current, startText, text }) {
  if (current !== startText) return 'stale';
  if (text === startText) return 'noop';
  return 'apply';
}
