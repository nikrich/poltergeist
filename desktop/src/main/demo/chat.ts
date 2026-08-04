// Demo-mode chat — simulates a streaming Claude turn so the chat scene looks
// live, without any LLM call. Emits the same ChatStreamEvent vocabulary the
// real agent does (session → tool → delta… → done) and appends the finished
// turn to the demo conversation so the post-stream refetch renders it.

import type { ChatStreamEvent } from '../../shared/api-types';
import { appendTurn } from './fixtures';

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

// One canned answer — the driver types a matching question. Markdown renders
// with headings, a bullet list, and a vault-link reference.
const TOOL_SUMMARY = 'searched vault · 6 hits';
const ANSWER = `Here's a draft agenda for the 15:00 readiness review, built from the launch plan and the open items:

1. **Go / no-go owner** — confirm it's Maya (currently unassigned).
2. **Date** — Thursday next week, locked in standup this morning.
3. **Billing (AUR-142)** — dry-run clean; sign off on the currency-code reconcile.
4. **Rollout** — \`aurora_v2\` flag, 10% first, then full.
5. **Rollback** — agree the trigger and who pulls it.

Sources: [[Aurora launch plan — v4]], [[AUR-142]], [[#aurora-launch]].`;

const aborts = new Map<string, boolean>();

export function stopDemoChat(convId: string): void {
  aborts.set(convId, true);
}

export async function runDemoChatStream(
  convId: string,
  userText: string,
  send: (event: ChatStreamEvent) => void,
): Promise<{ ok: true } | { ok: false; error: string }> {
  aborts.set(convId, false);
  const aborted = () => aborts.get(convId) === true;

  send({ type: 'session', session_id: 'demo-session' });
  await sleep(450);
  if (aborted()) return { ok: true };

  // "Thinking" beat, then the search tool chip.
  send({ type: 'tool', name: 'search_vault', summary: TOOL_SUMMARY });
  await sleep(700);
  if (aborted()) return { ok: true };

  // Stream the answer in small chunks so the text types out naturally.
  const tokens = ANSWER.match(/\S+\s*/g) ?? [ANSWER];
  for (const tok of tokens) {
    if (aborted()) return { ok: true };
    send({ type: 'delta', text: tok });
    await sleep(28);
  }

  // Persist the turn before the terminal event — the renderer invalidates the
  // conversation query on `done`, and the refetch must include this exchange.
  appendTurn(userText, ANSWER, TOOL_SUMMARY);
  send({ type: 'done', text: ANSWER, session_id: 'demo-session' });
  aborts.delete(convId);
  return { ok: true };
}
