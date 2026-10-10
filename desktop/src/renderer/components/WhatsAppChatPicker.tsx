import { useMemo, useState } from 'react';

import { Btn } from './Btn';
import type { WhatsAppChat } from '../../shared/api-types';
import { useContexts, useSaveWhatsAppChats, useWhatsAppChats } from '../lib/api/hooks';

type Kind = 'all' | 'direct' | 'group';
type Choice = { allowed: boolean; context: string | null };

export function WhatsAppChatPicker() {
  const chats = useWhatsAppChats();
  const contexts = useContexts();
  const save = useSaveWhatsAppChats();
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState<Kind>('all');
  const [edits, setEdits] = useState<Record<string, Choice>>({});

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (chats.data ?? []).filter(
      (c) => (kind === 'all' || c.kind === kind) && (!q || c.name.toLowerCase().includes(q)),
    );
  }, [chats.data, query, kind]);

  if (chats.isLoading) return <div className="text-12 text-ink-2">loading chats…</div>;
  if (chats.error) {
    return <div className="text-12 text-oxblood">{(chats.error as Error).message}</div>;
  }

  const current = (c: WhatsAppChat): Choice =>
    edits[c.jid] ?? { allowed: c.allowed, context: c.context };
  const edit = (c: WhatsAppChat, next: Partial<Choice>) =>
    setEdits((e) => ({ ...e, [c.jid]: { ...current(c), ...next } }));
  // Select all / clear act on the rows the search + kind filter currently show,
  // and only record an edit where the state actually changes.
  const setAllowed = (allowed: boolean) =>
    setEdits((e) => {
      const next = { ...e };
      for (const c of rows) {
        const cur = next[c.jid] ?? { allowed: c.allowed, context: c.context };
        if (cur.allowed !== allowed) next[c.jid] = { ...cur, allowed };
      }
      return next;
    });
  const dirty = Object.keys(edits).length > 0;
  const active = contexts.data?.contexts ?? [];
  const all = chats.data ?? [];
  const selected = all.filter((c) => current(c).allowed).length;

  return (
    <div className="flex flex-col gap-2">
      <div className="text-11 text-ink-2">
        Nothing is imported until you tick a chat. A newly ticked chat&apos;s first sync pulls the
        last 90 days.
      </div>
      <div className="flex items-center gap-[6px]">
        <input
          className="min-w-0 flex-1 rounded-r6 border border-hairline-2 bg-vellum px-2 py-1 text-12 text-ink-0"
          placeholder="search chats"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {(['all', 'direct', 'group'] as const).map((k) => (
          <button
            key={k}
            type="button"
            className={`rounded-r6 border px-2 py-1 text-11 ${
              kind === k
                ? 'border-hairline-2 bg-vellum text-ink-0'
                : 'border-transparent text-ink-2 hover:bg-vellum'
            }`}
            onClick={() => setKind(k)}
          >
            {k === 'group' ? 'groups' : k}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-[6px] text-11">
        <span className="flex-1 font-mono text-ink-2">{`${selected} of ${all.length} selected`}</span>
        {(
          [
            ['select all', true],
            ['clear', false],
          ] as const
        ).map(([label, allowed]) => (
          <button
            key={label}
            type="button"
            disabled={rows.length === 0}
            className="rounded-r6 border border-transparent px-2 py-1 text-ink-1 hover:bg-vellum disabled:opacity-40"
            onClick={() => setAllowed(allowed)}
          >
            {`${label} (${rows.length})`}
          </button>
        ))}
      </div>
      <ul className="flex max-h-[320px] flex-col gap-1 overflow-y-auto">
        {rows.map((c) => {
          const cur = current(c);
          const archivedContext =
            cur.context !== null && !active.includes(cur.context) ? cur.context : null;
          return (
            <li
              key={c.jid}
              className="flex items-center gap-2 rounded-r6 border border-hairline bg-paper px-3 py-[6px] text-12"
            >
              <input
                type="checkbox"
                aria-label={`include ${c.name}`}
                checked={cur.allowed}
                onChange={(e) => edit(c, { allowed: e.target.checked })}
              />
              <span className="min-w-0 flex-1 truncate text-ink-0">{c.name}</span>
              <span className="text-11 text-ink-3">{c.kind}</span>
              <span className="w-[80px] text-right font-mono text-11 text-ink-3">
                {c.lastMessageAt ? c.lastMessageAt.slice(0, 10) : '—'}
              </span>
              <select
                aria-label={`context for ${c.name}`}
                className="rounded-r6 border border-hairline-2 bg-vellum px-2 py-1 font-mono text-11 text-ink-0 disabled:opacity-40"
                value={cur.context ?? ''}
                disabled={!cur.allowed}
                onChange={(e) => edit(c, { context: e.target.value || null })}
              >
                <option value="">default</option>
                {active.map((ctx) => (
                  <option key={ctx} value={ctx}>
                    {ctx}
                  </option>
                ))}
                {archivedContext !== null && (
                  <option value={archivedContext}>{`${archivedContext} (archived)`}</option>
                )}
              </select>
            </li>
          );
        })}
      </ul>
      <div className="flex items-center gap-3">
        <Btn
          variant="secondary"
          size="sm"
          disabled={!dirty || save.isPending}
          onClick={() => save.mutate(edits, { onSuccess: () => setEdits({}) })}
        >
          save
        </Btn>
        {save.error && (
          <span role="alert" className="text-12 text-oxblood">
            {(save.error as Error).message}
          </span>
        )}
      </div>
    </div>
  );
}
