import { useEffect, useMemo, useRef, useState } from 'react';
import { BUDGETS } from '../ai/llm.js';
import { polishDocument, polishUnits } from '../ai/polish.js';
import { POLISH_PASSES } from '../ai/prompts.js';

export function PolishDialog({ plugin, text, onDone, onCancel }) {
  const [passes, setPasses] = useState(() => POLISH_PASSES.filter((p) => p.default).map((p) => p.id));
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);
  const ctrl = useRef(null);
  const sections = useMemo(() => polishUnits(text).units.length, [text]);
  useEffect(() => () => ctrl.current?.abort(), []);

  const toggle = (id) => setPasses((ps) => (ps.includes(id) ? ps.filter((p) => p !== id) : [...ps, id]));

  async function run() {
    setError(null);
    ctrl.current = new AbortController();
    setProgress({ done: 0, total: sections });
    try {
      const result = await polishDocument(plugin, { text, passes, onProgress: setProgress, signal: ctrl.current.signal });
      onDone({ ...result, original: text });
    } catch (err) {
      if (!ctrl.current?.signal.aborted) setError(err.message);
      setProgress(null);
    }
  }

  function cancel() {
    ctrl.current?.abort();
    onCancel();
  }

  return (
    <div className="sw-modal" role="dialog" aria-label="Polish">
      <div className="sw-dialog">
        <h2 style={{ marginTop: 0 }}>Polish script</h2>
        {POLISH_PASSES.map((p) => (
          <label key={p.id} className="sw-pl-pass">
            <input type="checkbox" checked={passes.includes(p.id)} disabled={!!progress} onChange={() => toggle(p.id)} />
            <span><strong>{p.label}</strong><br /><span className="sw-muted">{p.rule}</span></span>
          </label>
        ))}
        <p className="sw-muted">
          {sections} {sections === 1 ? 'section' : 'sections'} &middot; {sections} AI calls, at most ${(sections * BUDGETS.polishPerSection).toFixed(2)} &middot; you review every change before it lands
        </p>
        {progress && (
          <div className="sw-progress" aria-label="Polish progress">
            <div style={{ width: `${Math.round((100 * progress.done) / Math.max(1, progress.total))}%` }} />
            <span className="sw-muted">{progress.done} / {progress.total}</span>
          </div>
        )}
        {error && <div className="sw-status sw-err">{error}</div>}
        <div className="sw-row">
          <button type="button" className="sw-btn" onClick={cancel}>Cancel</button>
          <button type="button" className="sw-btn sw-primary" disabled={!!progress || passes.length === 0} onClick={run}>{progress ? 'Polishing\u2026' : 'Polish'}</button>
        </div>
      </div>
    </div>
  );
}
