import { useEffect, useState } from 'react';
import { Btn } from '../components/Btn';
import { OntologyBacklog } from '../components/OntologyBacklog';
import { OntologyGraph } from '../components/OntologyGraph';
import { PanelEmpty } from '../components/PanelEmpty';
import { PanelError } from '../components/PanelError';
import { Pill } from '../components/Pill';
import { SkeletonRows } from '../components/SkeletonRows';
import { TopBar } from '../components/TopBar';
import { toast } from '../stores/toast';
import { useOntologyView } from '../stores/ontology-view';
import {
  useEnableOntologyProject, useOntologyProjects, useOntologyTopics, useOntologyStatus, useRegistryProjects,
} from '../lib/api/ontology-hooks';

export function OntologyScreen() {
  const status = useOntologyStatus();
  const projects = useOntologyProjects();
  const { project, tab, setProject, setTab } = useOntologyView();
  const [enabling, setEnabling] = useState(false);

  useEffect(() => {
    if (project === null && projects.data && projects.data.length > 0) setProject(projects.data[0]!.uuid);
  }, [project, projects.data, setProject]);

  const current = projects.data?.find((p) => p.uuid === project) ?? projects.data?.[0] ?? null;
  const unavailable = status.data !== undefined && !status.data.available;

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar
        title="ontology"
        subtitle={current ? `${current.name} · ${current.bound} sources · ${current.pending_items} waiting` : 'ratified project knowledge'}
        right={
          <div className="flex items-center gap-2">
            {projects.data && projects.data.length > 0 && (
              <select aria-label="ontology project" value={current?.uuid ?? ''} onChange={(e) => setProject(e.target.value)}
                      className="rounded-sm border border-hairline-2 bg-paper px-2 py-1 font-mono text-11 text-ink-0">
                {projects.data.map((p) => <option key={p.uuid} value={p.uuid}>{p.name}</option>)}
              </select>
            )}
            <Btn variant="secondary" size="sm" onClick={() => setEnabling((v) => !v)}>enable project</Btn>
          </div>
        }
      />
      {unavailable ? (
        <PanelError message={`ontology unavailable: ${status.data?.reason ?? 'unknown reason'}`} onRetry={() => void status.refetch()} />
      ) : status.isError ? (
        <PanelError message={String(status.error)} onRetry={() => void status.refetch()} />
      ) : projects.isError ? (
        <PanelError message={String(projects.error)} onRetry={() => void projects.refetch()} />
      ) : (
        <>
      {enabling && <EnableForm onDone={() => setEnabling(false)} />}
      {projects.isLoading && <SkeletonRows count={3} height={48} />}
      {projects.data && projects.data.length === 0 && !enabling && (
        <PanelEmpty icon="network" message="no project has an ontology yet" />
      )}
      {current && (
        <>
          <div className="flex flex-shrink-0 items-center gap-[6px] border-b border-hairline px-6 py-3" role="tablist">
            {(['backlog', 'graph'] as const).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} type="button" onClick={() => setTab(t)}
                      className={`rounded-sm border px-[10px] py-1 font-mono text-11 ${tab === t ? 'border-neon/30 bg-neon/15 text-neon-ink' : 'border-hairline-2 text-ink-1'}`}>
                {t}
              </button>
            ))}
          </div>
          <Boundary project={current.uuid} />
          {tab === 'backlog'
            ? <OntologyBacklog project={current.uuid} projectName={current.name} />
            : <OntologyGraph project={current.uuid} />}
        </>
      )}
        </>
      )}
    </div>
  );
}

function Boundary({ project }: { project: string }) {
  const topics = useOntologyTopics(project);
  const inScope = (topics.data ?? []).filter((t) => t.status === 'in');
  const out = (topics.data ?? []).filter((t) => t.status === 'out');
  if (inScope.length === 0 && out.length === 0) return null;
  return (
    <div className="flex flex-shrink-0 flex-wrap items-center gap-[6px] border-b border-hairline px-6 py-2" aria-label="project boundary">
      <span className="font-mono text-11 text-ink-3">boundary</span>
      {inScope.map((t) => <Pill key={t.uid} tone="moss">{t.name} · {t.notes}</Pill>)}
      {out.map((t) => <Pill key={t.uid} tone="oxblood" className="line-through">{t.name} · {t.notes}</Pill>)}
    </div>
  );
}

function EnableForm({ onDone }: { onDone: () => void }) {
  const registry = useRegistryProjects();
  const enable = useEnableOntologyProject();
  const setProject = useOntologyView((s) => s.setProject);
  const [projectId, setProjectId] = useState('');
  const [seeds, setSeeds] = useState('');
  const submit = () =>
    enable.mutate(
      { project_id: projectId, seeds: seeds.split(',').map((s) => s.trim()).filter(Boolean) },
      {
        onSuccess: (p) => { setProject(p.uuid); onDone(); },
        onError: (e) => toast.error(String(e)),
      },
    );
  return (
    <div className="flex flex-shrink-0 items-end gap-3 border-b border-hairline bg-vellum px-6 py-3">
      <label className="flex flex-col font-mono text-11 text-ink-2">
        project
        <select aria-label="project to enable" value={projectId} onChange={(e) => setProjectId(e.target.value)}
                className="rounded-sm border border-hairline-2 bg-paper px-2 py-1 text-ink-0">
          <option value="">choose…</option>
          {(registry.data ?? []).filter((p) => !p.archived).map((p) => <option key={p.id} value={p.id}>{p.name} ({p.context})</option>)}
        </select>
      </label>
      <label className="flex flex-1 flex-col font-mono text-11 text-ink-2">
        seed terms (comma-separated)
        <input aria-label="seed terms" value={seeds} onChange={(e) => setSeeds(e.target.value)} placeholder="project name, ticket key"
               className="rounded-sm border border-hairline-2 bg-paper px-2 py-1 text-ink-0" />
      </label>
      <Btn variant="primary" size="sm" disabled={!projectId || !seeds.trim() || enable.isPending} onClick={submit}>
        {enable.isPending ? 'scanning…' : 'enable'}
      </Btn>
    </div>
  );
}
