import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const renderPage = vi.fn(async (..._a: unknown[]) => {});
const pageSize = vi.fn(async (n: number, _s: number) => (n === 2 ? { width: 200, height: 100 } : { width: 100, height: 140 }));
vi.mock('../components/docs/pdf', () => ({
  loadPdf: vi.fn(async () => ({ numPages: 10, renderPage, pageSize: (n: number, sc: number) => pageSize(n, sc) })),
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
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { cb(0); return 1; });
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

  it('sizes each placeholder from its own page once known', async () => {
    await open();
    fire(margin(), [entry(1, 1), entry(2, 1)]);
    await waitFor(() => expect((pageEl(2) as HTMLElement).style.width).toBe('200px'));
    expect((pageEl(2) as HTMLElement).style.height).toBe('100px');
    expect((pageEl(3) as HTMLElement).style.width).toBe('100px');
  });

  it('derives the current page from scroll position, so End then ← goes to N-1', async () => {
    await open();
    const sc = document.querySelector('[tabindex="0"]') as HTMLElement;
    Object.defineProperty(sc, 'clientHeight', { value: 500, configurable: true });
    Object.defineProperty(sc, 'scrollHeight', { value: 2000, configurable: true });
    for (let n = 1; n <= 10; n++) Object.defineProperty(pageEl(n), 'offsetTop', { value: (n - 1) * 200, configurable: true });
    sc.scrollTop = 450;
    fireEvent.scroll(sc);
    expect(screen.getByLabelText('go to page').textContent).toBe('3');
    fireEvent.keyDown(sc, { key: 'End' });
    sc.scrollTop = 1500; // max scroll: page 10 top is not at the viewport top
    fireEvent.scroll(sc);
    expect(screen.getByLabelText('go to page').textContent).toBe('10');
    fireEvent.keyDown(sc, { key: 'ArrowLeft' });
    expect(scrollIntoView).toHaveBeenLastCalledWith(pageEl(9));
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

  it('+ / - / 0 change zoom and preventDefault; modified keys are left alone', async () => {
    await open();
    const scroller = document.querySelector('[tabindex="0"]')!;
    const press = (key: string, mod: KeyboardEventInit = {}) => {
      const ev = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...mod });
      act(() => { scroller.dispatchEvent(ev); });
      return ev;
    };
    expect(press('=').defaultPrevented).toBe(true);
    expect(screen.getByText('125%')).toBeTruthy();
    expect((pageEl(1) as HTMLElement).style.height).toBe('175px');
    expect(press('+', { shiftKey: true }).defaultPrevented).toBe(true);
    expect(screen.getByText('150%')).toBeTruthy();
    expect(press('-').defaultPrevented).toBe(true);
    expect(press('-').defaultPrevented).toBe(true);
    expect(screen.getByText('100%')).toBeTruthy();
    expect(press('=', { metaKey: true }).defaultPrevented).toBe(false);
    expect(press('-', { ctrlKey: true }).defaultPrevented).toBe(false);
    expect(screen.getByText('100%')).toBeTruthy();
    press('=');
    press('0');
    expect(screen.getByText('100%')).toBeTruthy();
  });

  it('after zoom only pages near the viewport render at the new scale', async () => {
    await open();
    fire(margin(), [entry(1, 1), entry(2, 1), entry(3, 1)]);
    await waitFor(() => expect(renderPage).toHaveBeenCalledTimes(3));
    fire(margin(), [entry(2, 0), entry(3, 0)]);
    renderPage.mockClear();
    fireEvent.keyDown(document.querySelector('[tabindex="0"]')!, { key: '=' });
    await waitFor(() => expect(renderPage).toHaveBeenCalledWith(expect.anything(), 1, 1.25));
    expect(renderPage.mock.calls.map((c) => c[1])).toEqual([1]);
  });

  it('ignores keys from inputs', async () => {
    await open();
    const input = document.createElement('input');
    document.querySelector('[tabindex="0"]')!.appendChild(input);
    fireEvent.keyDown(input, { key: 'ArrowRight' });
    fireEvent.keyDown(input, { key: '=' });
    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(screen.getByText('100%')).toBeTruthy();
  });

  it('does not steal focus from an input elsewhere', async () => {
    const other = document.createElement('input');
    document.body.appendChild(other);
    other.focus();
    await open();
    expect(document.activeElement).toBe(other);
    other.remove();
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
