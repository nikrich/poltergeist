import { useRef } from 'react';

export function CharacterList({ characters, onJump }) {
  const next = useRef(new Map());
  return (
    <div>
      <div className="sw-h">Characters &middot; {characters.length}</div>
      {characters.map((c) => (
        <div key={c.name} className="sw-char" title="Click to cycle through their speeches"
          onClick={() => {
            const k = (next.current.get(c.name) ?? 0) % c.lines.length;
            next.current.set(c.name, k + 1);
            onJump(c.lines[k]);
          }}>
          <span>{c.name}</span><span className="sw-muted">{c.count}</span>
        </div>
      ))}
    </div>
  );
}
