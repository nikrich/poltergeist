import { useState } from 'react';

export function SceneNav({ scenes, cursorLine, onJump, onMove }) {
  const [drag, setDrag] = useState(null);
  const [over, setOver] = useState(null);
  const active = scenes.reduce((cur, s) => (s.line <= cursorLine ? s.index : cur), -1);
  return (
    <div>
      <div className="sw-h">Scenes &middot; {scenes.length}</div>
      {scenes.map((s) => (
        <div key={`${s.line}-${s.heading}`} draggable
          className={`sw-scene${s.index === active ? ' sw-active' : ''}${over === s.index && drag !== null ? ' sw-over' : ''}`}
          onClick={() => onJump(s.line)}
          onDragStart={() => setDrag(s.index)}
          onDragOver={(e) => { e.preventDefault(); setOver(s.index); }}
          onDragLeave={() => setOver(null)}
          onDrop={(e) => { e.preventDefault(); if (drag !== null && drag !== s.index) onMove(drag, s.index); setDrag(null); setOver(null); }}
          onDragEnd={() => { setDrag(null); setOver(null); }}>
          <span className="sw-num">{s.number}</span>{s.heading}
          {s.synopsis && <div className="sw-syn">{s.synopsis}</div>}
        </div>
      ))}
    </div>
  );
}
