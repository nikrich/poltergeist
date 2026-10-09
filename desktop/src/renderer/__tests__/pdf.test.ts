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

vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker.js' }));
vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: {},
  getDocument: () => ({
    promise: Promise.resolve({
      numPages: 1,
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
    }),
  }),
}));

import { cancelRender, renderThumb } from '../components/docs/pdf';

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
