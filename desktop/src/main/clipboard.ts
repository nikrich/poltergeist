import { clipboard, ipcMain } from 'electron';

export interface RichClipboardPayload {
  /** Rich flavour — what Slack/Confluence/Teams paste. */
  html: string;
  /** Plain flavour — the markdown equivalent, for terminals/editors. */
  text: string;
}

function isRichClipboardPayload(value: unknown): value is RichClipboardPayload {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { html?: unknown }).html === 'string' &&
    typeof (value as { text?: unknown }).text === 'string'
  );
}

export function installClipboardBridge(): void {
  // Re-install safety: a second ipcMain.handle for the same channel throws.
  ipcMain.removeHandler('gb:clipboard:write-rich');
  ipcMain.handle('gb:clipboard:write-rich', (_e, payload: unknown) => {
    if (!isRichClipboardPayload(payload)) {
      return {
        ok: false as const,
        error: 'write-rich: expected { html: string, text: string }',
      };
    }
    try {
      clipboard.write({ html: payload.html, text: payload.text });
      return { ok: true as const };
    } catch (err) {
      return {
        ok: false as const,
        error: err instanceof Error ? err.message : String(err),
      };
    }
  });
}
