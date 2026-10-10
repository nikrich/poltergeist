import { useRef } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, get, post } from './client';
import { toast } from '../../stores/toast';
import type {
  OntologyActionBody, OntologyExtractStatus, OntologyGraph, OntologyItem, OntologyNodeDetail, OntologyProject,
  OntologyStatus, OntologyTopic, RegistryProject,
} from '../../../shared/api-types';

const KEY = ['ontology'] as const;

export function useOntologyStatus() {
  return useQuery({ queryKey: [...KEY, 'status'], queryFn: () => get<OntologyStatus>('/v1/ontology/status'), staleTime: 15_000 });
}

export function useOntologyProjects() {
  return useQuery({ queryKey: [...KEY, 'projects'], queryFn: () => get<OntologyProject[]>('/v1/ontology/projects') });
}

export function useRegistryProjects() {
  return useQuery({ queryKey: [...KEY, 'registry'], queryFn: () => get<RegistryProject[]>('/v1/projects') });
}

export function useEnableOntologyProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { project_id: string; seeds: string[] }) => post<OntologyProject>('/v1/ontology/projects/enable', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useOntologyBacklog(project: string | null) {
  return useQuery({
    queryKey: [...KEY, 'backlog', project],
    queryFn: () => get<OntologyItem[]>(`/v1/ontology/backlog?project=${encodeURIComponent(project!)}`),
    enabled: project !== null,
  });
}

export function useOntologyTopics(project: string | null) {
  return useQuery({
    queryKey: [...KEY, 'topics', project],
    queryFn: () => get<OntologyTopic[]>(`/v1/ontology/projects/${project!}/topics`),
    enabled: project !== null,
  });
}

export function useOntologyAction(project: string | null) {
  const qc = useQueryClient();
  const inFlight = useRef(false);
  const m = useMutation({
    mutationFn: ({ itemId, body }: { itemId: number; body: OntologyActionBody }) =>
      post<{ ok: boolean; seq: number | null }>(`/v1/ontology/backlog/${itemId}/action`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [...KEY, 'backlog', project] });
      void qc.invalidateQueries({ queryKey: [...KEY, 'graph', project] });
      void qc.invalidateQueries({ queryKey: [...KEY, 'projects'] });
      void qc.invalidateQueries({ queryKey: [...KEY, 'topics'] });
      void qc.invalidateQueries({ queryKey: [...KEY, 'node'] });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) {
        // Already decided elsewhere: not a failure, just refresh the list.
        toast.info('already decided');
        void qc.invalidateQueries({ queryKey: [...KEY, 'backlog', project] });
        return;
      }
      toast.error(e instanceof Error ? e.message : String(e));
    },
    onSettled: () => { inFlight.current = false; },
  });
  // isPending only flips after React Query's async notify, so a ref closes the
  // double-click window between the first click and the re-render.
  const mutate: typeof m.mutate = (vars, opts) => {
    if (inFlight.current) return;
    inFlight.current = true;
    m.mutate(vars, opts);
  };
  return { ...m, mutate };
}

export function useOntologyExtractStatus(project: string | null) {
  return useQuery({
    queryKey: [...KEY, 'extract', project],
    queryFn: () => get<OntologyExtractStatus>(`/v1/ontology/projects/${project!}/extract`),
    enabled: project !== null,
    refetchInterval: (q) => (q.state.data?.running ? 2_000 : false),
  });
}

export function useStartOntologyExtract(project: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (limit: number) => post<OntologyExtractStatus>(`/v1/ontology/projects/${project!}/extract`, { limit }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [...KEY, 'extract', project] });
      void qc.invalidateQueries({ queryKey: [...KEY, 'backlog', project] });
    },
  });
}

export function useOntologyGraph(project: string | null, focus: string | null, depth: number) {
  const q = focus ? `&focus=${encodeURIComponent(focus)}` : '';
  return useQuery({
    queryKey: [...KEY, 'graph', project, focus, depth],
    queryFn: () => get<OntologyGraph>(`/v1/ontology/graph?project=${encodeURIComponent(project!)}&depth=${depth}${q}`),
    enabled: project !== null,
    placeholderData: keepPreviousData,
  });
}

export function useOntologyNode(uid: string | null) {
  return useQuery({
    queryKey: [...KEY, 'node', uid],
    queryFn: () => get<OntologyNodeDetail>(`/v1/ontology/nodes/${encodeURIComponent(uid!)}`),
    enabled: uid !== null,
  });
}
