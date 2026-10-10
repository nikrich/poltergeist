import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, patch, post } from './client';
import type {
  TemplateDiagnostic,
  TemplateDryRunRequest,
  TemplateDryRunResponse,
  TemplateLintResponse,
  TemplateQueryValues,
  TemplateRegistry,
  TemplateSaveResponse,
  TemplateSourceResponse,
} from '../../../shared/api-types';

/** Template editor (C3) calls. Every key starts with 'templates', so
 * invalidating ['templates'] after a save refreshes the list too. */

const enc = encodeURIComponent;

export function useTemplateFunctions() {
  return useQuery({
    queryKey: ['templates', 'functions'],
    queryFn: () => get<TemplateRegistry>('/v1/templates/functions'),
    staleTime: Infinity,
  });
}

export function useTemplateQueryValues() {
  return useQuery({
    queryKey: ['templates', 'query-values'],
    queryFn: () => get<TemplateQueryValues>('/v1/templates/query-values'),
    staleTime: 60_000,
    // A cold link index answers indexing: true; ask again shortly.
    refetchInterval: (q) => (q.state.data?.indexing ? 3_000 : false),
  });
}

export function useTemplateSource(id: string | null) {
  return useQuery({
    queryKey: ['templates', 'source', id],
    queryFn: () => get<TemplateSourceResponse>(`/v1/templates/${enc(id ?? '')}/source`),
    enabled: id !== null,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export function lintTemplate(source: string): Promise<TemplateDiagnostic[]> {
  return post<TemplateLintResponse>('/v1/templates/lint', { source }).then((r) => r.diagnostics);
}

/** `etag` null = overwrite whatever is on disk (the conflict banner's "keep mine"). */
export function saveTemplateSource(
  id: string,
  source: string,
  etag: string | null,
): Promise<TemplateSaveResponse> {
  return patch<TemplateSaveResponse>(`/v1/templates/${enc(id)}/source`, { source }, { ifMatch: etag });
}

export function useCreateBlankTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => post<TemplateSaveResponse>('/v1/templates', { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['templates'] }),
  });
}

export function useTemplateDryRun() {
  return useMutation({
    mutationFn: (req: Omit<TemplateDryRunRequest, 'dry_run'>) =>
      post<TemplateDryRunResponse>('/v1/templates/render', { ...req, dry_run: true }),
  });
}
