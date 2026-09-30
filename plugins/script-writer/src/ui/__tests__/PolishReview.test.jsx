// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import { polishUnits } from '../../ai/polish.js';
import { PolishReview } from '../PolishReview.jsx';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const DOC = 'INT. A - DAY\n\nmara wait.\n\nMARA\nNow?\n\nINT. B - DAY\n\nGo.\n';

function makeResult(doc = DOC) {
  const { sb, units } = polishUnits(doc);
  const results = units.map((u) => ({ ...u, polished: u.text, status: 'unchanged' }));
  results[0] = { ...results[0], status: 'changed', summary: 'grammar', polished: 'INT. A - DAY\n\nMara waits.\n\nMARA\nNow?\n\nShe sits.' };
  results[1] = { ...results[1], status: 'error', reason: 'Budget exceeded' };
  return { sb, results, original: doc };
}

async function mountReview(result, onApply = () => {}) {
  const el = document.createElement('div');
  document.body.appendChild(el);
  const root = createRoot(el);
  await act(async () => { root.render(<PolishReview result={result} onApply={onApply} onClose={() => {}} />); });
  return { el, root };
}

describe('PolishReview', () => {
  it('lists changes and flags, and applies only the kept changes', async () => {
    const onApply = vi.fn();
    const { el, root } = await mountReview(makeResult(), onApply);
    expect(el.textContent).toContain('2 changes');
    expect(el.textContent).toContain('Budget exceeded');
    expect(el.textContent).not.toContain('tidies the spacing');
    const boxes = el.querySelectorAll('input[type=checkbox]');
    expect(boxes).toHaveLength(2);
    await act(async () => { boxes[1].click(); });
    await act(async () => { [...el.querySelectorAll('button')].find((b) => b.textContent === 'Apply').click(); });
    expect(onApply).toHaveBeenCalledWith('INT. A - DAY\n\nMara waits.\n\nMARA\nNow?\n\nINT. B - DAY\n\nGo.\n');
    act(() => root.unmount());
  });

  it('notes that applying tidies scene spacing when the original spacing is not canonical', async () => {
    const { el, root } = await mountReview(makeResult('INT. A - DAY\n\nmara wait.\n\nMARA\nNow?\n\n\n\n\nINT. B - DAY\n\nGo.\n'));
    expect(el.textContent).toContain('Applying also tidies the spacing between scenes.');
    act(() => root.unmount());
  });
});
