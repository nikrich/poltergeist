// @vitest-environment jsdom
import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { FormatBar } from '../FormatBar.jsx';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe('FormatBar', () => {
  it('runs actions on click (keyboard-reachable) and not on mousedown', () => {
    const onEmphasis = vi.fn();
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => root.render(createElement(FormatBar, { currentType: 'action', onSetType: () => {}, onEmphasis, onNewScene: () => {} })));
    const bold = host.querySelector('button[title^="Bold"]');
    const md = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
    act(() => { bold.dispatchEvent(md); });
    expect(md.defaultPrevented).toBe(true);
    expect(onEmphasis).not.toHaveBeenCalled();
    act(() => { bold.click(); });
    expect(onEmphasis).toHaveBeenCalledTimes(1);
    expect(onEmphasis).toHaveBeenCalledWith('bold');
    act(() => root.unmount());
  });
});
