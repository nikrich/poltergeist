import { toast } from '../stores/toast';

let warned = false;

/** Spec A3: a user save whose history snapshot failed still succeeds; tell
 * the user once per session, not on every autosave. */
export function reportHistoryHealth(res: { historyOk?: boolean } | null | undefined): void {
  if (warned || res?.historyOk !== false) return;
  warned = true;
  toast.error('history unavailable — your edits are saved, but no version was kept');
}

export function resetHistoryHealthForTests(): void {
  warned = false;
}
