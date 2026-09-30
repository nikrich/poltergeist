// Debounced autosave that never drops text: failures retry with backoff and
// the latest unsaved content is mirrored to the plugin data dir.
export const BACKOFF_MS = [2000, 4000, 8000, 16000, 30000];

export function createSaver({ save, mirror, onStatus = () => {}, delayMs = 1500 }) {
  let pending = null;
  let timer = null;
  let inflight = null;
  let attempt = 0;
  let disposed = false;
  let status = 'saved';
  const setStatus = (s, info) => { status = s; onStatus(s, info); };
  const schedule = (ms) => { clearTimeout(timer); timer = setTimeout(run, ms); };

  function run() {
    timer = null;
    if (pending === null || inflight) return inflight ?? Promise.resolve();
    const content = pending;
    pending = null;
    setStatus('saving');
    inflight = (async () => {
      try {
        await save(content);
        attempt = 0;
        if (pending === null) setStatus('saved');
        else if (!disposed) schedule(delayMs);
      } catch (err) {
        if (pending === null) pending = content;
        const wait = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
        attempt++;
        setStatus('error', { message: err?.message ?? String(err), retryInMs: wait });
        try { await mirror(pending); } catch { /* best effort: the editor still holds the text */ }
        if (!disposed) schedule(wait);
      } finally {
        inflight = null;
      }
    })();
    return inflight;
  }

  return {
    change(content) {
      pending = content;
      if (status === 'error') return; // keep the backoff schedule during an outage
      setStatus('dirty');
      schedule(delayMs);
    },
    async flush() {
      clearTimeout(timer);
      timer = null;
      if (inflight) await inflight;
      if (pending !== null) await run();
    },
    dispose() {
      disposed = true;
      clearTimeout(timer);
    },
    get status() { return status; },
  };
}

export function shouldOfferDraft(draft, meta, body) {
  if (!draft || typeof draft.content !== 'string' || draft.content === body) return false;
  return String(draft.savedAt ?? '') > String(meta?.updated ?? '');
}
