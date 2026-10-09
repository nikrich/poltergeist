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

const cache = new Map<string, Promise<PDFDocumentProxy>>();

function open(url: string): Promise<PDFDocumentProxy> {
  let p = cache.get(url);
  if (!p) {
    p = getDocument({ url }).promise;
    p.catch(() => cache.delete(url));
    cache.set(url, p);
  }
  return p;
}

export async function loadPdf(url: string): Promise<PdfHandle> {
  const pdf = await open(url);
  return {
    numPages: pdf.numPages,
    async renderPage(canvas, pageNo, scale) {
      const gen = bump(canvas);
      const page = await pdf.getPage(pageNo);
      if (currentGen(canvas) !== gen) return;
      const ratio = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: scale * ratio });
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.width = `${viewport.width / ratio}px`;
      canvas.style.height = `${viewport.height / ratio}px`;
      await runRender(canvas, () => page.render({ canvasContext: canvas.getContext('2d')!, viewport }));
    },
  };
}

export async function renderThumb(canvas: HTMLCanvasElement, url: string, width: number): Promise<void> {
  const gen = bump(canvas);
  const pdf = await open(url);
  if (currentGen(canvas) !== gen) return;
  const page = await pdf.getPage(1);
  if (currentGen(canvas) !== gen) return;
  const base = page.getViewport({ scale: 1 });
  const viewport = page.getViewport({ scale: width / base.width });
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  await runRender(canvas, () => page.render({ canvasContext: canvas.getContext('2d')!, viewport }));
}
