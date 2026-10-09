import { beforeEach, describe, expect, it, vi } from 'vitest';

const tasks: Array<{ cancel: ReturnType<typeof vi.fn>; reject: (e: unknown) => void; resolve: () => void }> = [];

vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker.js' }));
vi.mock('pdfjs-dist', () => {
  const page = {
    getViewport: ({ scale }: { scale: number }) => ({ width: 100 * scale, height: 140 * scale }),
    render: vi.fn(() => {
      let resolve!: () => void;
      let reject!: (e: unknown) => void;
      const promise = new Promise<void>((res, rej) => { resolve = res; reject = rej; });
      const t = {
        promise,
        resolve,
        reject,
        cancel: vi.fn(() => reject(Object.assign(new Error('cancelled'), { name: 'RenderingCancelledException' }))),
      };
      tasks.push(t);
      return t;
    }),
  };
  return {
    GlobalWorkerOptions: {},
    getDocument: () => ({ promise: Promise.resolve({ numPages: 1, getPage: async () => page }) }),
  };
});

import { renderThumb } from '../components/docs/pdf';

describe('pdf render cancellation', () => {
  beforeEach(() => {
    tasks.length = 0;
  });

  it('cancels the in-flight render on the same canvas; the first call resolves', async () => {
    const canvas = document.createElement('canvas');
    canvas.getContext = vi.fn(() => ({})) as never;
    const first = renderThumb(canvas, 'gbdoc://a.pdf', 160);
    await vi.waitFor(() => expect(tasks).toHaveLength(1));
    const second = renderThumb(canvas, 'gbdoc://a.pdf', 160);
    await vi.waitFor(() => expect(tasks).toHaveLength(2));
    expect(tasks[0]!.cancel).toHaveBeenCalledTimes(1);
    await expect(first).resolves.toBeUndefined();
    tasks[1]!.resolve();
    await expect(second).resolves.toBeUndefined();
  });
});
