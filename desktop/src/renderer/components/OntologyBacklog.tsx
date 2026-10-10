import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Btn } from './Btn';
import { Lucide } from './Lucide';
import { PanelEmpty } from './PanelEmpty';
import { PanelError } from './PanelError';
import { SkeletonRows } from './SkeletonRows';
import { Pill } from './Pill';
import { ScopeCard } from './ScopeCard';
import { toast } from '../stores/toast';
import { useNoteView } from '../stores/note-view';
import {
  useOntologyAction, useOntologyBacklog, useOntologyExtractStatus, useStartOntologyExtract,
} from '../lib/api/ontology-hooks';
import type { OntologyItem } from '../../shared/api-types';

export function OntologyBacklog({ project, projectName }: { project: string; projectName: string }) {
  const backlog = useOntologyBacklog(project);
  const extract = useOntologyExtractStatus(project);
  const start = useStartOntologyExtract(project);
  const running = extract.data?.running ?? false;
  const qc = useQueryClient();
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) {
      void qc.invalidateQueries({ queryKey: ['ontology', 'backlog', project] });
      void qc.invalidateQueries({ queryKey: ['ontology', 'projects'] });
    }
    wasRunning.current = running;
  }, [running, project, qc]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex flex-shrink-0 items-center gap-3 border-b border-hairline px-6 py-3">
        <Btn variant="secondary" size="sm" disabled={running || start.isPending}
             icon={<Lucide name="sparkles" size={13} />}
             onClick={() => start.mutate(25, { onError: (e) => toast.error(e instanceof Error ? e.message : String(e)) })}>
          {running ? 'extracting…' : 'extract next 25'}
        </Btn>
        {extract.data?.last_error && <span className="font-mono text-11 text-oxblood">{extract.data.last_error}</span>}
        {extract.data?.summary && !running && (
          <span className="font-mono text-11 text-ink-3">
            last run: {String(extract.data.summary.processed ?? 0)} notes · {String(extract.data.summary.new ?? 0)} new
          </span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-3">
        {backlog.isLoading && <SkeletonRows count={4} height={72} />}
        {backlog.isError && <PanelError message={String(backlog.error)} onRetry={() => void backlog.refetch()} />}
        {backlog.data && backlog.data.length === 0 && (
          <PanelEmpty icon="check-circle" message="nothing waiting for ratification" />
        )}
        {backlog.data?.map((item) =>
          item.type === 'scope'
            ? <ScopeCard key={item.id} project={project} projectName={projectName} item={item} />
            : item.type === 'binding'
              ? <BindingRow key={item.id} project={project} projectName={projectName} item={item} />
              : <CandidateRow key={item.id} project={project} item={item} />,
        )}
      </div>
    </div>
  );
}

function BindingRow({ project, projectName, item }: { project: string; projectName: string; item: OntologyItem }) {
  const action = useOntologyAction(project);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const toggle = (aid: string) =>
    setExcluded((s) => { const n = new Set(s); if (n.has(aid)) n.delete(aid); else n.add(aid); return n; });
  return (
    <div className="mb-2 rounded-r6 border border-hairline px-[14px] py-[10px]">
      <div className="mb-2 flex items-center gap-2">
        <Pill tone="neon">binding</Pill>
        <span className="text-13 text-ink-0">{item.artefacts.length} notes look like {projectName}</span>
      </div>
      <ul className="mb-2 max-h-48 overflow-y-auto">
        {item.artefacts.map((a) => (
          <li key={a.aid} className="flex items-center gap-2 py-[2px] font-mono text-11 text-ink-1">
            <input type="checkbox" aria-label={`include ${a.title}`} checked={!excluded.has(a.aid)} onChange={() => toggle(a.aid)} />
            <span className="truncate">{a.title}</span>
            <span className="truncate text-ink-3">{a.path}</span>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Btn variant="primary" size="sm" ariaLabel={`ratify binding ${item.id}`}
             disabled={action.isPending || item.artefacts.length - excluded.size === 0}
             onClick={() => action.mutate({ itemId: item.id, body: { action: 'ratify', exclude: [...excluded] } })}>
          ratify {item.artefacts.length - excluded.size}
        </Btn>
        <Btn variant="ghost" size="sm" disabled={action.isPending}
             onClick={() => action.mutate({ itemId: item.id, body: { action: 'reject' } })}>
          reject all
        </Btn>
      </div>
    </div>
  );
}

function CandidateRow({ project, item }: { project: string; item: OntologyItem }) {
  const c = item.candidate!;
  const action = useOntologyAction(project);
  const openNote = useNoteView((s) => s.open);
  const [value, setValue] = useState(c.value ?? '');
  const edited = c.value !== null && value !== c.value;
  const ratify = () =>
    action.mutate({ itemId: item.id, body: edited ? { action: 'ratify', value } : { action: 'ratify' } });
  return (
    <div className="mb-2 rounded-r6 border border-hairline px-[14px] py-[10px]">
      <div className="mb-1 flex items-center gap-2">
        <Pill tone="outline">{c.kind}</Pill>
        <span className="text-13 text-ink-0">{c.name}</span>
        <span className="ml-auto font-mono text-9 text-ink-3">{Math.round(c.confidence * 100)}%</span>
      </div>
      <p className="mb-2 text-13 text-ink-1">{c.statement}</p>
      {c.value !== null && (
        <label className="mb-2 flex items-center gap-2 font-mono text-11 text-ink-2">
          value
          <input aria-label={`value for ${c.name}`} value={value} onChange={(e) => setValue(e.target.value)}
                 className="rounded-sm border border-hairline-2 bg-paper px-2 py-[2px] text-ink-0" />
        </label>
      )}
      <ul className="mb-2">
        {c.evidence.map((e, i) => (
          <li key={`${e.aid}-${i}`} className="font-mono text-11 text-ink-2">
            “{e.quote}” —{' '}
            <button type="button" className="text-neon-ink underline" onClick={() => e.path && openNote(e.path)}>
              {e.title}
            </button>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Btn variant="primary" size="sm" ariaLabel={`ratify ${c.name}`} disabled={action.isPending} onClick={ratify}>ratify</Btn>
        <Btn variant="ghost" size="sm" ariaLabel={`reject ${c.name}`} disabled={action.isPending}
             onClick={() => action.mutate({ itemId: item.id, body: { action: 'reject' } })}>reject</Btn>
        <Btn variant="ghost" size="sm" ariaLabel={`investigate ${c.name}`} disabled={action.isPending}
             onClick={() => action.mutate({ itemId: item.id, body: { action: 'investigate' } })}>investigate</Btn>
      </div>
    </div>
  );
}
