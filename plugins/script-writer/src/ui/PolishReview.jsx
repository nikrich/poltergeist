import { useMemo, useState } from 'react';
import { composePolished } from '../ai/polish.js';
import { hunks, wordDiff } from '../diff/lineDiff.js';

function Words({ a, b }) {
  return (
    <>
      <div className="sw-pl-del">{wordDiff(a, b).filter((p) => p.type !== 'add').map((p, i) => <span key={i} className={p.type === 'del' ? 'sw-w-del' : ''}>{p.text}</span>)}</div>
      <div className="sw-pl-add">{wordDiff(a, b).filter((p) => p.type !== 'del').map((p, i) => <span key={i} className={p.type === 'add' ? 'sw-w-add' : ''}>{p.text}</span>)}</div>
    </>
  );
}

export function PolishReview({ result, onApply, onClose }) {
  const items = useMemo(() => result.results.map((r, u) => ({
    r, u, hs: r.status === 'changed' ? hunks(r.text.split('\n'), r.polished.split('\n')) : [],
  })), [result]);
  const keys = useMemo(() => items.flatMap(({ u, hs }) => hs.filter((h) => h.type === 'change').map((_, c) => `${u}:${c}`)), [items]);
  const [off, setOff] = useState(() => new Set());
  const flagged = items.filter(({ r }) => r.status === 'rejected' || r.status === 'error');
  const toggle = (k) => setOff((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const normalises = composePolished(result, () => false) !== result.original;
  const apply = () => onApply(composePolished(result, (u, c) => !off.has(`${u}:${c}`)));

  return (
    <div className="sw-modal" role="dialog" aria-label="Polish review">
      <div className="sw-dialog sw-polish-review">
        <div className="sw-row" style={{ justifyContent: 'space-between', marginTop: 0 }}>
          <h2 style={{ margin: 0 }}>Polish review</h2>
          <span className="sw-muted">{keys.length} {keys.length === 1 ? 'change' : 'changes'} &middot; {keys.length - off.size} kept</span>
        </div>
        {flagged.length > 0 && (
          <div className="sw-pl-flags">
            {flagged.map(({ r, u }) => <div key={u} className="sw-status sw-err">{r.heading}: kept original ({r.reason})</div>)}
          </div>
        )}
        {normalises && <p className="sw-muted">Applying also tidies the spacing between scenes.</p>}
        {keys.length === 0 && <p className="sw-muted">Nothing to change &mdash; the script already reads clean for the passes you picked.</p>}
        <div className="sw-pl-list">
          {items.filter(({ hs }) => hs.length).map(({ r, u, hs }) => {
            let c = -1;
            return (
              <section key={u} className="sw-pl-scene">
                <h3>{r.heading}{r.summary ? <span className="sw-muted"> &mdash; {r.summary}</span> : null}</h3>
                {hs.map((h, i) => {
                  if (h.type === 'equal') return h.lines.length > 2 ? <div key={i} className="sw-pl-eq sw-muted">&hellip; {h.lines.length} unchanged lines</div> : <div key={i} className="sw-pl-eq">{h.lines.join('\n')}</div>;
                  c += 1;
                  const k = `${u}:${c}`;
                  return (
                    <label key={i} className={`sw-pl-hunk${off.has(k) ? ' sw-pl-off' : ''}`}>
                      <input type="checkbox" checked={!off.has(k)} onChange={() => toggle(k)} />
                      <div className="sw-pl-body">
                        {h.del.length === 1 && h.add.length === 1 ? <Words a={h.del[0]} b={h.add[0]} /> : (
                          <>
                            {h.del.length > 0 && <div className="sw-pl-del">{h.del.join('\n')}</div>}
                            {h.add.length > 0 && <div className="sw-pl-add">{h.add.join('\n')}</div>}
                          </>
                        )}
                      </div>
                    </label>
                  );
                })}
              </section>
            );
          })}
        </div>
        <div className="sw-row">
          <button type="button" className="sw-btn" onClick={() => setOff(new Set())}>Accept all</button>
          <button type="button" className="sw-btn" onClick={() => setOff(new Set(keys))}>Reject all</button>
          <span className="sw-grow" />
          <button type="button" className="sw-btn" onClick={onClose}>Close</button>
          <button type="button" className="sw-btn sw-primary" disabled={keys.length === 0} onClick={apply}>Apply</button>
        </div>
      </div>
    </div>
  );
}
