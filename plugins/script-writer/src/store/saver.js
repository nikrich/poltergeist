// Debounced autosave that never drops text: failures retry with backoff and
// the latest unsaved content is mirrored to the plugin data dir.
export const BACKOFF_MS = [2000, 4000, 8000, 16000, 30000];

export function createSaver({ save, mirror, onStatus = () => {}, delayMs = 1500 }) {
  let pending = null;
  let timer = null;
  let inflight = null;
  let mirrorInFlight = null;
  let mirrorNeeded = false;
  let attempt = 0;
  let disposed = false;
  let status = 'saved';
  const setStatus = (s, info) => { status = s; try { onStatus(s, info); } catch { /* ignore onStatus errors */ } };
  const schedule = (ms) => { clearTimeout(timer); timer = setTimeout(run, ms); };

  async function mirrorLatest() {
    const toMirror = pending;
    if (mirrorInFlight) {
      mirrorNeeded = true;
      return;
    }
    mirrorInFlight = (async () => {
      try {
        await mirror(toMirror);
      } catch { /* best effort: the editor still holds the text */ }
      mirrorInFlight = null;
      if (mirrorNeeded) {
        mirrorNeeded = false;
        await mirrorLatest();
      }
    })();
    await mirrorInFlight;
  }

  function run() {
    clearTimeout(timer);
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
        else { setStatus('dirty'); if (!disposed) schedule(delayMs); }
      } catch (err) {
        if (pending === null) pending = content;
        const wait = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
        attempt++;
        setStatus('error', { message: err?.message ?? String(err), retryInMs: wait });
        await mirrorLatest();
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
      if (disposed) return; // no-op after dispose
      if (status === 'error') { mirrorLatest(); return; } // keep backoff schedule, mirror latest
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
      if (pending !== null && status !== 'error') mirrorLatest(); // best effort: mirror pending if not already mirrored in catch
    },
    get status() { return status; },
  };
}

export function shouldOfferDraft(draft, meta, body) {
  if (!draft || typeof draft.content !== 'string' || draft.content === body) return false;
  return String(draft.savedAt ?? '') > String(meta?.updated ?? '');
}
