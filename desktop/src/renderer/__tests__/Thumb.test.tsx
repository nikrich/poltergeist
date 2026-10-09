import { act, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../components/docs/pdf', () => ({
  renderThumb: vi.fn(async () => {}),
  cancelRender: vi.fn(),
  loadPdf: vi.fn(),
}));

import { renderThumb } from '../components/docs/pdf';
import { Thumb } from '../components/docs/Thumb';
import { doc } from './fixtures/library';

describe('Thumb', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('renders a PDF thumbnail only once the card intersects the viewport', () => {
    const observers: Array<{ cb: IntersectionObserverCallback; disconnect: ReturnType<typeof vi.fn> }> = [];
    vi.stubGlobal('IntersectionObserver', class {
      disconnect = vi.fn();
      constructor(cb: IntersectionObserverCallback) {
        observers.push({ cb, disconnect: this.disconnect });
      }
      observe() {}
      unobserve() {}
    });
    render(<Thumb doc={doc({})} />);
    expect(renderThumb).not.toHaveBeenCalled();
    act(() => observers[0]!.cb([{ isIntersecting: false } as IntersectionObserverEntry], {} as IntersectionObserver));
    expect(renderThumb).not.toHaveBeenCalled();
    act(() => observers[0]!.cb([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver));
    expect(renderThumb).toHaveBeenCalledTimes(1);
    expect(vi.mocked(renderThumb).mock.calls[0]![1]).toBe(
      'gbdoc://doc/20-contexts/work/projects/payments/docs/specs/Payments%20API%20v2.pdf?v=aaaaaaaaaaaa',
    );
    expect(observers[0]!.disconnect).toHaveBeenCalled();
  });

  it('renders immediately where IntersectionObserver is unavailable', () => {
    vi.stubGlobal('IntersectionObserver', undefined);
    render(<Thumb doc={doc({})} />);
    expect(renderThumb).toHaveBeenCalledTimes(1);
  });
});
