import { useEffect, useRef, useState } from 'react';

export function Overlay() {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const [body, setBody] = useState('');

  useEffect(() => {
    ref.current?.focus();
  }, []);

  useEffect(() => {
    const off = window.gb.jot.onFocus(() => {
      setBody('');
      ref.current?.focus();
    });
    return off;
  }, []);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Escape') {
      e.preventDefault();
      window.gb.jot.cancel();
      return;
    }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      const trimmed = body.trim();
      if (!trimmed) return;
      window.gb.jot.save(trimmed);
      setBody('');
    }
  }

  return (
    <div className="flex h-screen w-screen flex-col rounded-md border border-hairline bg-paper/95 backdrop-blur-md p-4">
      <textarea
        ref={ref}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="jot a thought…"
        className="flex-1 resize-none bg-transparent text-14 text-ink-0 outline-none"
        autoFocus
      />
      <div className="flex justify-between pt-2 font-mono text-10 text-ink-3">
        <span>⌘↵ save · esc cancel</span>
        <span>poltergeist</span>
      </div>
    </div>
  );
}
