import type { Conversation } from '../../shared/api-types';

const defaultSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Auto-filing runs in the background after the first reply; poll the chat
 *  until it settles so the sidebar can move it and show the notice. */
export async function waitForAutoFile(
  convId: string,
  fetchConv: (id: string) => Promise<Conversation>,
  { intervalMs = 1500, maxTries = 20, sleep = defaultSleep }: { intervalMs?: number; maxTries?: number; sleep?: (ms: number) => Promise<void> } = {},
): Promise<Conversation | null> {
  for (let i = 0; i < maxTries; i++) {
    try {
      const conv = await fetchConv(convId);
      if (conv.auto_filed !== 'pending') return conv;
    } catch {
      return null;
    }
    if (i < maxTries - 1) await sleep(intervalMs);
  }
  return null;
}
