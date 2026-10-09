import { beforeEach, describe, expect, it, vi } from 'vitest';

interface FakeTask {
  cancel: ReturnType<typeof vi.fn>;
  reject: (e: unknown) => void;
  resolve: () => void;
  promise: Promise<void>;
}
const tasks: FakeTask[] = [];
const renders: Array<{ width: number }> = [];
let getPageGate: Promise<void> | null = null;
let nextWidth = 100;
const opened: Array<{ url: string; destroy: ReturnType<typeof vi.fn> }> = [];

vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker.js' }));
vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: {},
  getDocument: ({ url }: { url: string }) => {
    const destroy = vi.fn(async () => {});
    opened.push({ url, destroy });
    return { promise: Promise.resolve({
      numPages: 1,
      destroy,
      getPage: async () => {
        const gate = getPageGate;
        const width = nextWidth;
        if (gate) await gate;
        return {
          getViewport: ({ scale }: { scale: number }) => ({ width: width * scale, height: 140 * scale }),
          render: vi.fn(() => {
            renders.push({ width });
            let resolve!: () => void;
            let reject!: (e: unknown) => void;
            const promise = new Promise<void>((res, rej) => { resolve = res; reject = rej; });
            const t: FakeTask = {
              promise, resolve, reject,
              cancel: vi.fn(() => reject(Object.assign(new Error('cancelled'), { name: 'RenderingCancelledException' }))),
            };
            tasks.push(t);
            return t;
          }),
        };
      },
    }) };
  },
}));

import { cancelRender, MAX_OPEN_DOCS, openDocUrls, renderThumb } from '../components/docs/pdf';

function makeCanvas(): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.getContext = vi.fn(() => ({})) as never;
  return canvas;
}

describe('pdf render cancellation', () => {
  beforeEach(() => {
    tasks.length = 0;
    renders.length = 0;
    getPageGate = null;
    nextWidth = 100;
  });

  it('cancels the in-flight render on the same canvas; the first call resolves', async () => {
    const canvas = makeCanvas();
    const first = renderThumb(canvas, 'gbdoc://a.pdf', 160);
    await vi.waitFor(() => expect(tasks).toHaveLength(1));
    const second = renderThumb(canvas, 'gbdoc://a.pdf', 160);
    await vi.waitFor(() => expect(tasks).toHaveLength(2));
    expect(tasks[0]!.cancel).toHaveBeenCalledTimes(1);
    await expect(first).resolves.toBeUndefined();
    tasks[1]!.resolve();
    await expect(second).resolves.toBeUndefined();
  });

  it('a stale call resuming after a newer one never touches the canvas', async () => {
    const canvas = makeCanvas();
    let release!: () => void;
    getPageGate = new Promise<void>((r) => { release = r; });
    nextWidth = 50; // page A
    const a = renderThumb(canvas, 'gbdoc://a.pdf', 160);
    await Promise.resolve();
    getPageGate = null;
    nextWidth = 200; // page B
    const b = renderThumb(canvas, 'gbdoc://a.pdf', 160);
    await vi.waitFor(() => expect(tasks).toHaveLength(1));
    const bWidth = canvas.width;
    release();
    await expect(a).resolves.toBeUndefined();
    expect(renders).toEqual([{ width: 200 }]);
    expect(tasks[0]!.cancel).not.toHaveBeenCalled();
    expect(canvas.width).toBe(bWidth);
    tasks[0]!.resolve();
    await expect(b).resolves.toBeUndefined();
  });

  it('cancelRender during a pending getPage prevents the render', async () => {
    const canvas = makeCanvas();
    let release!: () => void;
    getPageGate = new Promise<void>((r) => { release = r; });
    const a = renderThumb(canvas, 'gbdoc://a.pdf', 160);
    await Promise.resolve();
    cancelRender(canvas);
    release();
    await expect(a).resolves.toBeUndefined();
    expect(renders).toHaveLength(0);
    expect(canvas.width).toBe(300); // jsdom default, untouched
  });
});

describe('pdf document cache', () => {
  beforeEach(() => {
    tasks.length = 0;
    renders.length = 0;
    opened.length = 0;
    getPageGate = null;
  });

  async function thumb(url: string): Promise<void> {
    const n = tasks.length;
    const p = renderThumb(makeCanvas(), url, 160);
    await vi.waitFor(() => expect(tasks).toHaveLength(n + 1));
    tasks[n]!.resolve();
    await p;
  }

  it('keeps at most 8 documents and destroys the least recently used', async () => {
    expect(MAX_OPEN_DOCS).toBe(8);
    const base = 'gbdoc://lru-';
    for (let i = 0; i < 8; i++) await thumb(`${base}${i}.pdf`);
    await thumb(`${base}0.pdf`); // touch 0 → 1 is now the oldest
    expect(opened.filter((o) => o.url.startsWith(base))).toHaveLength(8);
    await thumb(`${base}8.pdf`);
    const mine = openDocUrls().filter((u) => u.startsWith(base));
    expect(mine).toHaveLength(8);
    expect(mine).not.toContain(`${base}1.pdf`);
    expect(mine).toContain(`${base}0.pdf`);
    await vi.waitFor(() => expect(opened.find((o) => o.url === `${base}1.pdf`)!.destroy).toHaveBeenCalledTimes(1));
    expect(opened.filter((o) => o.url !== `${base}1.pdf`).every((o) => o.destroy.mock.calls.length === 0)).toBe(true);
    await thumb(`${base}1.pdf`); // evicted docs reopen on demand
    expect(opened.filter((o) => o.url === `${base}1.pdf`)).toHaveLength(2);
  });

  it('never destroys a document while a render is using it', async () => {
    const base = 'gbdoc://busy-';
    const n = tasks.length;
    const busy = renderThumb(makeCanvas(), `${base}held.pdf`, 160);
    await vi.waitFor(() => expect(tasks).toHaveLength(n + 1));
    for (let i = 0; i < 9; i++) await thumb(`${base}${i}.pdf`);
    const held = opened.find((o) => o.url === `${base}held.pdf`)!;
    expect(held.destroy).not.toHaveBeenCalled();
    expect(openDocUrls()).toContain(`${base}held.pdf`);
    expect(openDocUrls()[0]).toBe(`${base}held.pdf`); // oldest, yet kept while busy
    tasks[n]!.resolve();
    await busy;
    await thumb(`${base}next.pdf`); // now idle, it is the first to go
    expect(openDocUrls()).toHaveLength(8);
    expect(openDocUrls()).not.toContain(`${base}held.pdf`);
    await vi.waitFor(() => expect(held.destroy).toHaveBeenCalledTimes(1));
  });
});
