// Main-process entry: drafts in dataDir, file dialogs, and PDF printing
// through a hidden BrowserWindow. Renderer owns all vault I/O.
import { BrowserWindow, dialog } from 'electron';
import { mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { basename, join } from 'node:path';
import { clearDraft, readDraft, writeDraft } from './main/drafts.js';
import { clearThread, readThread, writeThread } from './main/threads.js';
import { EXPORT_EXTS, IMPORT_EXTS, MAX_IMPORT_BYTES, exportName, inlineFonts, withTimeout } from './main/files.js';

const PDF_TIMEOUT_MS = 30_000;

let ctx = null;
const printWindows = new Set();

const withParent = (fn, opts) => {
  const parent = BrowserWindow.getFocusedWindow();
  return parent ? fn(parent, opts) : fn(opts);
};

async function exportFile(req) {
  const { defaultName, ext, content } = req ?? {};
  if (!EXPORT_EXTS.includes(ext)) throw new Error(`export-file: unsupported extension ${JSON.stringify(ext)}`);
  if (typeof content !== 'string') throw new Error('export-file: content must be a string');
  const r = await withParent(dialog.showSaveDialog.bind(dialog), {
    defaultPath: exportName(defaultName, ext), filters: [{ name: ext === 'fountain' ? 'Fountain' : 'Text', extensions: [ext] }],
  });
  if (r.canceled || !r.filePath) return { canceled: true };
  writeFileSync(r.filePath, content, 'utf-8');
  return { path: r.filePath };
}

async function importFile() {
  const r = await withParent(dialog.showOpenDialog.bind(dialog), {
    properties: ['openFile'], filters: [{ name: 'Screenplay', extensions: IMPORT_EXTS }],
  });
  if (r.canceled || !r.filePaths?.length) return { canceled: true };
  const file = r.filePaths[0];
  if (statSync(file).size > MAX_IMPORT_BYTES) throw new Error(`${basename(file)} is larger than 5 MB`);
  return { name: basename(file), content: readFileSync(file, 'utf-8') };
}

async function exportPdf(req) {
  const c = ctx;
  if (!c) throw new Error('script-writer is not active');
  const { html, defaultName, paper } = req ?? {};
  if (typeof html !== 'string' || !html.startsWith('<!doctype html>')) throw new Error('export-pdf: expected an html document');
  const r = await withParent(dialog.showSaveDialog.bind(dialog), {
    defaultPath: exportName(defaultName, 'pdf'), filters: [{ name: 'PDF', extensions: ['pdf'] }],
  });
  if (r.canceled || !r.filePath) return { canceled: true };
  if (!ctx) throw new Error('script-writer is not active');
  const tmpDir = join(c.dataDir, 'tmp');
  mkdirSync(tmpDir, { recursive: true });
  const tmp = join(tmpDir, `print-${Date.now()}-${Math.random().toString(36).slice(2)}.html`);
  writeFileSync(tmp, inlineFonts(html, join(c.pluginDir, 'dist', 'fonts')), 'utf-8');
  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true } });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (e) => e.preventDefault());
  printWindows.add(win);
  try {
    const pdf = await withTimeout((async () => {
      await win.loadFile(tmp);
      await win.webContents.executeJavaScript('document.fonts.ready.then(() => true)');
      // printToPDF ignores print()'s marginType and defaults to 0.4in; zero it
      // explicitly so the page CSS owns the screenplay margins.
      return win.webContents.printToPDF({
        pageSize: paper === 'a4' ? 'A4' : 'Letter',
        printBackground: true,
        preferCSSPageSize: true,
        margins: { top: 0, bottom: 0, left: 0, right: 0 },
      });
    })(), PDF_TIMEOUT_MS, 'PDF export timed out');
    writeFileSync(r.filePath, pdf);
    return { path: r.filePath };
  } finally {
    printWindows.delete(win);
    if (!win.isDestroyed()) win.destroy();
    rmSync(tmp, { force: true });
  }
}

export function activate(context) {
  ctx = context;
  ctx.ipc.handle('draft-write', (req) => writeDraft(ctx.dataDir, req ?? {}));
  ctx.ipc.handle('draft-read', (key) => readDraft(ctx.dataDir, key));
  ctx.ipc.handle('draft-clear', (key) => clearDraft(ctx.dataDir, key));
  ctx.ipc.handle('thread-read', (key) => readThread(ctx.dataDir, key));
  ctx.ipc.handle('thread-write', (req) => writeThread(ctx.dataDir, req ?? {}));
  ctx.ipc.handle('thread-clear', (key) => clearThread(ctx.dataDir, key));
  ctx.ipc.handle('export-file', exportFile);
  ctx.ipc.handle('import-file', importFile);
  ctx.ipc.handle('export-pdf', exportPdf);
  ctx.log('activated');
}

export function deactivate() {
  for (const w of printWindows) if (!w.isDestroyed()) w.destroy();
  printWindows.clear();
  ctx = null;
}
