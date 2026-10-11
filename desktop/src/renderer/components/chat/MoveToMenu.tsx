// desktop/src/renderer/components/chat/MoveToMenu.tsx
import { useEffect, useRef, useState } from 'react';
import type { ChatFolderNode, ChatLocation, ChatTree, ConversationSummary } from '../../../shared/api-types';
import { Lucide } from '../Lucide';

interface Item { key: string; label: string; depth: number; loc: ChatLocation }

function items(tree: ChatTree): Item[] {
  const out: Item[] = [{ key: 'unfiled', label: 'unfiled', depth: 0, loc: { context: null, project: null, folder: null } }];
  for (const s of tree.scopes) {
    if (s.archived) continue;
    const base = s.project ? 1 : 0;
    out.push({ key: `${s.context}/${s.project ?? '_'}/`, label: s.name, depth: base, loc: { context: s.context, project: s.project, folder: null } });
    const walk = (nodes: ChatFolderNode[], depth: number) => {
      for (const f of nodes) {
        out.push({ key: `${s.context}/${s.project ?? '_'}/${f.path}`, label: f.name, depth, loc: { context: s.context, project: s.project, folder: f.path } });
        walk(f.folders, depth + 1);
      }
    };
    walk(s.folders, base + 1);
  }
  return out;
}

const same = (a: ChatLocation, c: ConversationSummary) =>
  a.context === (c.context ?? null) && a.project === (c.project ?? null) && a.folder === (c.folder ?? null);

/** Hover button → menu of every location and folder; the non-drag path for moving a chat. */
export function MoveToMenu({ chat, tree, onMove }: { chat: ConversationSummary; tree: ChatTree; onMove: (loc: ChatLocation) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const choose = (loc: ChatLocation) => {
    setOpen(false);
    if (!same(loc, chat)) onMove(loc);
  };

  return (
    <span
      ref={ref}
      className="relative flex-shrink-0"
      onClick={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === 'Escape') setOpen(false);
      }}
    >
      <button
        type="button"
        aria-label={`move ${chat.title}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex h-[18px] w-[18px] items-center justify-center rounded-xs text-ink-3 opacity-0 transition-opacity hover:text-ink-0 focus:opacity-100 group-hover:opacity-100"
      >
        <Lucide name="folder-input" size={12} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-[22px] z-20 max-h-[260px] w-[200px] overflow-y-auto rounded-r6 border border-hairline-2 bg-vellum py-1 shadow-lg"
        >
          {items(tree).map((it) => (
            <button
              key={it.key}
              type="button"
              role="menuitem"
              onClick={() => choose(it.loc)}
              className={`flex w-full items-center gap-[6px] py-[6px] pr-3 text-left text-12 hover:bg-fog hover:text-ink-0 ${same(it.loc, chat) ? 'text-neon' : 'text-ink-1'}`}
              style={{ paddingLeft: 12 + it.depth * 12 }}
            >
              {it.loc.folder && <Lucide name="folder" size={11} className="opacity-70" />}
              <span className="truncate">{it.label}</span>
            </button>
          ))}
        </div>
      )}
    </span>
  );
}
