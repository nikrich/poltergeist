import { BrowserWindow, dialog, shell } from 'electron';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const PRINT_CSS = `
  body { font: 13px/1.6 -apple-system, 'Helvetica Neue', sans-serif; color: #1a1a1a;
         max-width: 700px; margin: 40px auto; padding: 0 24px; }
  h1, h2, h3 { line-height: 1.3; } pre, code { font: 11px/1.5 ui-monospace, monospace;
  background: #f5f5f5; border-radius: 4px; } pre { padding: 12px; overflow-x: hidden; }
  code { padding: 1px 4px; } table { border-collapse: collapse; }
  th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
  blockquote { border-left: 3px solid #ddd; margin-left: 0; padding-left: 16px; color: #555; }
`;

export function wrapPrintableHtml(title: string, bodyHtml: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title><style>${PRINT_CSS}</style></head><body>${bodyHtml}</body></html>`;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export async function exportPdf(
  parent: BrowserWindow | null,
  payload: { title: string; html: string },
): Promise<{ ok: true; path: string } | { ok: false; error: string } | { ok: false; cancelled: true }> {
  const safeName =
    payload.title.replace(/[/\\:*?"<>|]/g, '-').slice(0, 80) || 'document';
  const saveOptions: Electron.SaveDialogOptions = {
    defaultPath: `${safeName}.pdf`,
    filters: [{ name: 'PDF', extensions: ['pdf'] }],
  };
  // Use the parent-window overload when available so the dialog sheets onto
  // the window on macOS; fall back to the standalone overload when the sender
  // window is gone (e.g. hidden overlay) to avoid passing null/undefined.
  const picked = parent
    ? await dialog.showSaveDialog(parent, saveOptions)
    : await dialog.showSaveDialog(saveOptions);
  if (picked.canceled || !picked.filePath) return { ok: false, cancelled: true };

  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true } });
  // Load via a temp file, not a data: URL — Chromium caps URLs at ~2MB and
  // percent-encoding inflates the HTML ~3x, so long docs would silently fail.
  let tempDir: string | null = null;
  try {
    const html = wrapPrintableHtml(payload.title, payload.html);
    tempDir = await mkdtemp(join(tmpdir(), 'gb-pdf-'));
    const htmlPath = join(tempDir, 'doc.html');
    await writeFile(htmlPath, html, 'utf-8');
    await win.loadFile(htmlPath);
    const pdf = await win.webContents.printToPDF({ printBackground: true });
    await writeFile(picked.filePath, pdf);
    return { ok: true, path: picked.filePath };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  } finally {
    win.destroy();
    if (tempDir) await rm(tempDir, { recursive: true, force: true }).catch(() => {});
  }
}

export function isGeneratedDocPath(rel: string): boolean {
  const norm = rel.replace(/\\/g, '/');
  return (
    norm.startsWith('20-contexts/generated-docs/') &&
    norm.endsWith('.html') &&
    !norm.split('/').includes('..')
  );
}

export async function renderVaultHtmlToPdf(
  vaultPath: string,
  rel: string,
): Promise<{ ok: true; path: string } | { ok: false; error: string }> {
  if (!vaultPath) return { ok: false, error: 'vault path not configured' };
  if (!isGeneratedDocPath(rel)) {
    return { ok: false, error: 'path is not a generated doc' };
  }
  const htmlPath = join(vaultPath, rel);
  const pdfPath = htmlPath.replace(/\.html$/, '.pdf');
  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true, javascript: false } });
  try {
    // The agent's HTML is already a complete styled document — load as-is
    // (no wrapPrintableHtml), so its own CSS/@page rules drive the layout.
    await win.loadFile(htmlPath);
    const pdf = await win.webContents.printToPDF({ printBackground: true });
    await writeFile(pdfPath, pdf);
    await shell.openPath(pdfPath);
    return { ok: true, path: pdfPath };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  } finally {
    win.destroy();
  }
}
