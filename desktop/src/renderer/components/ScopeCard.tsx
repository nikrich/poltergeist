import { useState } from 'react';
import { Btn } from './Btn';
import { Pill } from './Pill';
import { useNoteView } from '../stores/note-view';
import { useOntologyAction } from '../lib/api/ontology-hooks';
import type { OntologyItem, OntologyScopeQuestion } from '../../shared/api-types';

const SAMPLE = 5;

const LEAN: Record<OntologyScopeQuestion['lean'], { tone: 'oxblood' | 'moss' | 'fog'; label: string }> = {
  not_about: { tone: 'oxblood', label: 'probably not' },
  about: { tone: 'moss', label: 'probably yes' },
  unclear: { tone: 'fog', label: 'unsure' },
};

export function ScopeCard({ project, projectName, item }: { project: string; projectName: string; item: OntologyItem }) {
  const q = item.scope!;
  const action = useOntologyAction(project);
  const openNote = useNoteView((s) => s.open);
  const [all, setAll] = useState(false);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const toggle = (aid: string) =>
    setExcluded((s) => { const n = new Set(s); if (n.has(aid)) n.delete(aid); else n.add(aid); return n; });
  const lean = LEAN[q.lean];
  const shown = all ? q.notes : q.notes.slice(0, SAMPLE);
  return (
    <div className="mb-2 rounded-r6 border border-hairline px-[14px] py-[10px]">
      <div className="mb-2 flex items-center gap-2">
        <Pill tone={lean.tone}>{lean.label}</Pill>
        <span className="text-13 text-ink-0">Is <strong>{q.name}</strong> part of <strong>{projectName}</strong>?</span>
      </div>
      <ul className="mb-2 max-h-48 overflow-y-auto">
        {shown.map((n) => (
          <li key={n.aid} className="flex items-center gap-2 py-[2px] font-mono text-11 text-ink-1">
            {all && (
              <input type="checkbox" aria-label={`include ${n.title}`} checked={!excluded.has(n.aid)} onChange={() => toggle(n.aid)} />
            )}
            <button type="button" className="truncate text-neon-ink underline" onClick={() => openNote(n.path)}>{n.title}</button>
            <span className="truncate text-ink-3">{n.reason}</span>
          </li>
        ))}
      </ul>
      {q.notes.length > 0 && (
        <button type="button" className="mb-2 font-mono text-11 text-ink-2 underline" onClick={() => setAll((v) => !v)}>
          {all ? 'show fewer' : `show all ${q.notes.length}`}
        </button>
      )}
      <div className="flex gap-2">
        <Btn variant="primary" size="sm" ariaLabel={`yes ${q.name}`} disabled={action.isPending}
             onClick={() => action.mutate({ itemId: item.id, body: { action: 'yes', exclude: [...excluded] } })}>yes</Btn>
        <Btn variant="ghost" size="sm" ariaLabel={`no ${q.name}`} disabled={action.isPending}
             onClick={() => action.mutate({ itemId: item.id, body: { action: 'no' } })}>no</Btn>
        <Btn variant="ghost" size="sm" ariaLabel={`not sure ${q.name}`} disabled={action.isPending}
             onClick={() => action.mutate({ itemId: item.id, body: { action: 'investigate' } })}>not sure</Btn>
      </div>
    </div>
  );
}
