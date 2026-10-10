import { Btn } from './Btn';
import { Lucide } from './Lucide';
import { PanelError } from './PanelError';
import { Pill } from './Pill';
import { SkeletonRows } from './SkeletonRows';
import { useOntologyNode } from '../lib/api/ontology-hooks';
import { useNoteView } from '../stores/note-view';
import { useOntologyView } from '../stores/ontology-view';

export function OntologyNodePanel({ uid }: { uid: string }) {
  const node = useOntologyNode(uid);
  const openNote = useNoteView((s) => s.open);
  const { setSelected, setFocus } = useOntologyView();
  const d = node.data;
  const notePath = d ? d.generated_note_path ?? d.note_path : null;

  return (
    <aside aria-label="node details" className="flex w-[320px] shrink-0 flex-col gap-4 overflow-y-auto border-l border-hairline bg-vellum p-6 text-13">
      <div className="flex items-start justify-between gap-2">
        {d ? (
          <div className="flex flex-col gap-2">
            <Pill tone="neon" className="self-start">{d.kind}</Pill>
            <h4 className="text-16 font-medium leading-tight text-ink-0">{d.name}</h4>
          </div>
        ) : <span />}
        <button type="button" aria-label="close details" onClick={() => setSelected(null)} className="text-ink-3 hover:text-ink-0">
          <Lucide name="x" size={14} />
        </button>
      </div>
      {node.isLoading && <SkeletonRows count={3} height={32} />}
      {node.isError && <PanelError message={String(node.error)} onRetry={() => void node.refetch()} />}
      {d && (
        <>
          {d.statement && <p className="text-ink-1">{d.statement}</p>}
          {d.value && <p className="text-ink-0"><span className="font-mono text-11 text-ink-3">value </span>{d.value}</p>}
          {(d.provenance || d.ratified_at) && (
            <p className="font-mono text-9 text-ink-3">
              {[d.provenance, d.ratified_at && `ratified ${d.ratified_at}`].filter(Boolean).join(' · ')}
            </p>
          )}
          {d.evidence.length > 0 && (
            <section>
              <h5 className="mb-1 font-mono text-11 text-ink-3">Evidence</h5>
              <ul className="flex flex-col gap-1">
                {d.evidence.map((e, i) => (
                  <li key={`${e.aid}-${i}`}>
                    <button type="button" disabled={!e.note_path} onClick={() => e.note_path && openNote(e.note_path)}
                            className="text-left text-ink-1 hover:text-ink-0">
                      {e.quote && <>“{e.quote}” — </>}<span className="text-ink-2">{e.title}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {d.relations.length > 0 && (
            <section>
              <h5 className="mb-1 font-mono text-11 text-ink-3">Related</h5>
              <ul className="flex flex-col gap-1">
                {d.relations.map((r) => (
                  <li key={`${r.direction}-${r.type}-${r.uid}`}>
                    <button type="button" onClick={() => setSelected(r.uid)} className="text-left text-ink-1 hover:text-ink-0">
                      <span className="font-mono text-11 text-ink-3">{r.direction === 'in' ? '←' : '→'} {r.type.toLowerCase()} </span>{r.name}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <div className="flex gap-2">
            {notePath && <Btn variant="secondary" size="sm" onClick={() => openNote(notePath)}>open note</Btn>}
            <Btn variant="secondary" size="sm" onClick={() => setFocus(uid)}>focus</Btn>
          </div>
        </>
      )}
    </aside>
  );
}
