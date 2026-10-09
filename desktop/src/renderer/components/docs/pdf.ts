// The only module that touches pdfjs-dist, so tests can mock it wholesale.
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

GlobalWorkerOptions.workerSrc = workerUrl;

export interface PdfHandle {
  numPages: number;
  renderPage(canvas: HTMLCanvasElement, page: number, scale: number): Promise<void>;
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
      const page = await pdf.getPage(pageNo);
      const ratio = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: scale * ratio });
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.width = `${viewport.width / ratio}px`;
      canvas.style.height = `${viewport.height / ratio}px`;
      await page.render({ canvasContext: canvas.getContext('2d')!, viewport }).promise;
    },
  };
}

export async function renderThumb(canvas: HTMLCanvasElement, url: string, width: number): Promise<void> {
  const pdf = await open(url);
  const page = await pdf.getPage(1);
  const base = page.getViewport({ scale: 1 });
  const viewport = page.getViewport({ scale: width / base.width });
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  await page.render({ canvasContext: canvas.getContext('2d')!, viewport }).promise;
}
