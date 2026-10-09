import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const renderPage = vi.fn(async (..._a: unknown[]) => {});
vi.mock('../components/docs/pdf', () => ({
  loadPdf: vi.fn(async () => ({ numPages: 10, renderPage, pageSize: async () => ({ width: 100, height: 140 }) })),
  renderThumb: vi.fn(async () => {}),
  cancelRender: vi.fn(),
}));

import { PdfViewer } from '../components/docs/PdfViewer';

interface FakeIO { cb: IntersectionObserverCallback; opts?: IntersectionObserverInit; els: Element[] }
let observers: FakeIO[] = [];
const scrollIntoView = vi.fn();

beforeEach(() => {
  observers = [];
  renderPage.mockClear();
  scrollIntoView.mockClear();
  Element.prototype.scrollIntoView = function (this: Element) { scrollIntoView(this); };
  vi.stubGlobal('IntersectionObserver', class {
    rec: FakeIO;
    constructor(cb: IntersectionObserverCallback, opts?: IntersectionObserverInit) {
      this.rec = { cb, opts, els: [] };
      observers.push(this.rec);
    }
    observe(el: Element) { this.rec.els.push(el); }
    disconnect() {}
    unobserve() {}
  });
});
afterEach(() => vi.unstubAllGlobals());

const margin = () => observers.find((o) => o.opts?.rootMargin)!;
const bare = () => observers.find((o) => !o.opts?.rootMargin)!;
const pageEl = (n: number) => document.querySelector(`[data-page="${n}"]`)!;
const entry = (n: number, ratio: number) =>
  ({ target: pageEl(n), isIntersecting: ratio > 0, intersectionRatio: ratio }) as unknown as IntersectionObserverEntry;
const fire = (o: FakeIO, entries: IntersectionObserverEntry[]) => act(() => o.cb(entries, {} as IntersectionObserver));

async function open() {
  render(<PdfViewer url="gbdoc://doc/a.pdf" />);
  await screen.findByText('/ 10');
}

describe('PdfViewer continuous scroll', () => {
  it('lays out a sized placeholder for every page and renders none until visible', async () => {
    await open();
    expect(document.querySelectorAll('[data-page]').length).toBe(10);
    expect((pageEl(7) as HTMLElement).style.height).toBe('140px');
    expect(renderPage).not.toHaveBeenCalled();
  });

  it('renders only pages reported intersecting', async () => {
    await open();
    fire(margin(), [entry(1, 1), entry(2, 0.4)]);
    await waitFor(() => expect(renderPage).toHaveBeenCalledTimes(2));
    expect(renderPage.mock.calls.map((c) => c[1]).sort()).toEqual([1, 2]);
    expect(pageEl(5).querySelector('canvas')).toBeNull();
  });

  it('pager follows the most visible page', async () => {
    await open();
    fire(bare(), [entry(1, 0.2), entry(2, 0.8)]);
    expect(screen.getByLabelText('go to page').textContent).toBe('2');
  });

  it('prev/next buttons, arrows, j/k and Home/End scroll the right page into view', async () => {
    await open();
    const scroller = document.querySelector('[tabindex="0"]')!;
    fireEvent.click(screen.getByLabelText('next page'));
    expect(scrollIntoView).toHaveBeenLastCalledWith(pageEl(2));
    fireEvent.keyDown(scroller, { key: 'ArrowRight' });
    expect(scrollIntoView).toHaveBeenLastCalledWith(pageEl(3));
    fireEvent.keyDown(scroller, { key: 'k' });
    expect(scrollIntoView).toHaveBeenLastCalledWith(pageEl(2));
    fireEvent.keyDown(scroller, { key: 'End' });
    expect(scrollIntoView).toHaveBeenLastCalledWith(pageEl(10));
    fireEvent.keyDown(scroller, { key: 'Home' });
    expect(scrollIntoView).toHaveBeenLastCalledWith(pageEl(1));
    fireEvent.click(screen.getByLabelText('previous page') as HTMLElement); // disabled on page 1: no-op
    expect(scrollIntoView).toHaveBeenCalledTimes(5);
  });

  it('jumps to a typed page number', async () => {
    await open();
    fireEvent.click(screen.getByLabelText('go to page'));
    const input = screen.getByLabelText('page number');
    fireEvent.change(input, { target: { value: '6' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(scrollIntoView).toHaveBeenLastCalledWith(pageEl(6));
  });

  it('cmd+= and cmd+- change zoom and preventDefault; cmd+0 resets', async () => {
    await open();
    const scroller = document.querySelector('[tabindex="0"]')!;
    const press = (key: string) => {
      const ev = new KeyboardEvent('keydown', { key, metaKey: true, bubbles: true, cancelable: true });
      act(() => { scroller.dispatchEvent(ev); });
      return ev;
    };
    expect(press('=').defaultPrevented).toBe(true);
    expect(screen.getByText('125%')).toBeTruthy();
    expect((pageEl(1) as HTMLElement).style.height).toBe('175px');
    expect(press('-').defaultPrevented).toBe(true);
    expect(press('-').defaultPrevented).toBe(true);
    expect(screen.getByText('75%')).toBeTruthy();
    press('0');
    expect(screen.getByText('100%')).toBeTruthy();
  });

  it('ignores keys from inputs', async () => {
    await open();
    const input = document.createElement('input');
    document.querySelector('[tabindex="0"]')!.appendChild(input);
    fireEvent.keyDown(input, { key: 'ArrowRight' });
    fireEvent.keyDown(input, { key: '=', metaKey: true });
    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(screen.getByText('100%')).toBeTruthy();
  });

  it('focuses the scroll container when the pdf opens', async () => {
    await open();
    await waitFor(() => expect(document.activeElement).toBe(document.querySelector('[tabindex="0"]')));
  });
});

describe('PdfViewer without IntersectionObserver', () => {
  it('renders the first 3 pages', async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal('IntersectionObserver', undefined);
    await open();
    await waitFor(() => expect(renderPage).toHaveBeenCalledTimes(3));
  });
});
