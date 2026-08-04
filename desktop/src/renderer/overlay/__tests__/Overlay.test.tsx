import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { Overlay } from '../Overlay';

const save = vi.fn();
const cancel = vi.fn();
const onFocusCb: { current: (() => void) | null } = { current: null };

beforeEach(() => {
  save.mockReset();
  cancel.mockReset();
  // @ts-expect-error — window.gb is normally injected by preload
  window.gb = {
    jot: {
      save,
      cancel,
      onFocus: (cb: () => void) => { onFocusCb.current = cb; return () => {}; },
      onSaveFailed: () => () => {},
    },
  };
});

describe('Overlay', () => {
  it('autofocuses the textarea on mount', () => {
    render(<Overlay />);
    const ta = screen.getByPlaceholderText('jot a thought…') as HTMLTextAreaElement;
    expect(document.activeElement).toBe(ta);
  });

  it('saves on ⌘+Enter', () => {
    render(<Overlay />);
    const ta = screen.getByPlaceholderText('jot a thought…');
    fireEvent.change(ta, { target: { value: 'a thought' } });
    fireEvent.keyDown(ta, { key: 'Enter', metaKey: true });
    expect(save).toHaveBeenCalledWith('a thought');
  });

  it('cancels on Escape', () => {
    render(<Overlay />);
    const ta = screen.getByPlaceholderText('jot a thought…');
    fireEvent.keyDown(ta, { key: 'Escape' });
    expect(cancel).toHaveBeenCalled();
  });

  it('does not save with empty body', () => {
    render(<Overlay />);
    const ta = screen.getByPlaceholderText('jot a thought…');
    fireEvent.keyDown(ta, { key: 'Enter', metaKey: true });
    expect(save).not.toHaveBeenCalled();
  });

  it('clears the textarea when onFocus fires (overlay re-opened)', () => {
    render(<Overlay />);
    const ta = screen.getByPlaceholderText('jot a thought…') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'old' } });
    expect(ta.value).toBe('old');
    act(() => { onFocusCb.current?.(); });
    expect(ta.value).toBe('');
  });
});
