// The only module that touches pdfjs-dist, so tests can mock it wholesale.
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy, type RenderTask } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

GlobalWorkerOptions.workerSrc = workerUrl;

export interface PdfHandle {
  numPages: number;
  renderPage(canvas: HTMLCanvasElement, page: number, scale: number): Promise<void>;
}

const inflight = new WeakMap<HTMLCanvasElement, RenderTask>();
const generations = new WeakMap<HTMLCanvasElement, number>();

const currentGen = (canvas: HTMLCanvasElement): number => generations.get(canvas) ?? 0;

// Invalidates every pending or running render on the canvas: stale calls that
// are still awaiting pdf.js bail out, and a running task is cancelled.
export function cancelRender(canvas: HTMLCanvasElement): void {
  generations.set(canvas, currentGen(canvas) + 1);
  inflight.get(canvas)?.cancel();
  inflight.delete(canvas);
}

function bump(canvas: HTMLCanvasElement): number {
  cancelRender(canvas);
  return currentGen(canvas);
}

// Runs a render task on the canvas. A cancelled render resolves quietly;
// real failures still reject.
async function runRender(canvas: HTMLCanvasElement, run: () => RenderTask): Promise<void> {
  const task = run();
  inflight.set(canvas, task);
  try {
    await task.promise;
  } catch (err) {
    if ((err as { name?: string } | null)?.name === 'RenderingCancelledException') return;
    throw err;
  } finally {
    if (inflight.get(canvas) === task) inflight.delete(canvas);
  }
}

// Small LRU of open documents (Map order = recency). An entry is only evicted —
// and its document destroyed — while no render is using it; a busy cache may sit
// above the cap briefly and shrinks again as renders finish.
export const MAX_OPEN_DOCS = 8;
interface Entry {
  promise: Promise<PDFDocumentProxy>;
  users: number;
}
const cache = new Map<string, Entry>();

function evict(): void {
  for (const [url, e] of cache) {
    if (cache.size <= MAX_OPEN_DOCS) return;
    if (e.users > 0) continue;
    cache.delete(url);
    e.promise.then((d) => d.destroy()).catch(() => {});
  }
}

async function withDoc<T>(url: string, fn: (pdf: PDFDocumentProxy) => Promise<T>): Promise<T> {
  let e = cache.get(url);
  if (e) {
    cache.delete(url); // touch: move to most-recent
  } else {
    const entry: Entry = { promise: getDocument({ url }).promise, users: 0 };
    entry.promise.catch(() => {
      if (cache.get(url) === entry) cache.delete(url);
    });
    e = entry;
  }
  cache.set(url, e);
  e.users++;
  evict();
  try {
    return await fn(await e.promise);
  } finally {
    e.users--;
    evict();
  }
}

/** Test hook: the cached document URLs, oldest first. */
export function openDocUrls(): string[] {
  return [...cache.keys()];
}

export async function loadPdf(url: string): Promise<PdfHandle> {
  const numPages = await withDoc(url, async (pdf) => pdf.numPages);
  return {
    numPages,
    // Re-acquires the document per render, so an evicted (destroyed) one is reopened.
    renderPage(canvas, pageNo, scale) {
      const gen = bump(canvas);
      return withDoc(url, async (pdf) => {
        if (currentGen(canvas) !== gen) return;
        const page = await pdf.getPage(pageNo);
        if (currentGen(canvas) !== gen) return;
        const ratio = window.devicePixelRatio || 1;
        const viewport = page.getViewport({ scale: scale * ratio });
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.style.width = `${viewport.width / ratio}px`;
        canvas.style.height = `${viewport.height / ratio}px`;
        await runRender(canvas, () => page.render({ canvasContext: canvas.getContext('2d')!, viewport }));
      });
    },
  };
}

export async function renderThumb(canvas: HTMLCanvasElement, url: string, width: number): Promise<void> {
  const gen = bump(canvas);
  await withDoc(url, async (pdf) => {
    if (currentGen(canvas) !== gen) return;
    const page = await pdf.getPage(1);
    if (currentGen(canvas) !== gen) return;
    const base = page.getViewport({ scale: 1 });
    const viewport = page.getViewport({ scale: width / base.width });
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    await runRender(canvas, () => page.render({ canvasContext: canvas.getContext('2d')!, viewport }));
  });
}
