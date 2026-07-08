import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import type {
  ImportSpace,
  ActivityRow,
  AgendaItem,
  AutoRouteResponse,
  AuthSessionView,
  ExtractPhotoResponse,
  Capture,
  CapturesPage,
  ConfluenceExportRequest,
  ConfluenceExportResponse,
  Connector,
  ConnectorDetail,
  Conversation,
  ConversationSummary,
  CreateJotRequest,
  CreateJotResponse,
  CreateProjectRequest,
  DailyPage,
  HeatmapResponse,
  JotsPage,
  MeetingsPage,
  Note,
  Prep,
  Project,
  RecorderSettings,
  RecorderStatus,
  SearchResponse,
  StartRecordingRequest,
  Suggestion,
  UpdateNoteBodyRequest,
  UpdateNoteBodyResponse,
  UpdateProjectRequest,
  UpdateRecorderSettings,
  VaultGraph,
  VaultStats,
  McpServersResponse,
  McpServerWrite,
} from '../../../shared/api-types';
import { del, get, patch, post, put } from './client';

export function useVaultStats() {
  return useQuery({
    queryKey: ['vault', 'stats'],
    queryFn: () => get<VaultStats>('/v1/vault/stats'),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

export function useVaultGraph() {
  return useQuery({
    queryKey: ['vault', 'graph'],
    queryFn: () => get<VaultGraph>('/v1/vault/graph'),
    staleTime: 60_000,
  });
}

export function useConnectors() {
  return useQuery({
    queryKey: ['connectors'],
    queryFn: () => get<Connector[]>('/v1/connectors'),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}

export function useConnector(id: string | null) {
  return useQuery({
    queryKey: ['connector', id],
    queryFn: () => get<ConnectorDetail>(`/v1/connectors/${id}`),
    enabled: id !== null,
    staleTime: 60_000,
  });
}

export function useCaptures(opts?: { limit?: number; source?: string }) {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  if (opts?.source) params.set('source', opts.source);
  const query = params.toString();
  return useQuery({
    queryKey: ['captures', opts ?? {}],
    // Signal piping is the load-bearing piece for filter switching:
    // when the user clicks a different chip, React Query aborts the
    // in-flight request for the previous source. Without this, a
    // refetched-in-background "all captures" response could land after
    // a brand-new "calendar" response and overwrite the visible list
    // with mixed data.
    queryFn: ({ signal }) =>
      get<CapturesPage>(
        `/v1/captures${query ? '?' + query : ''}`,
        { signal },
      ),
    // staleTime: 0 so chip clicks always trigger a fresh fetch (otherwise
    // the same-filter cache served back instantly and the next refetch
    // could overwrite again).
    staleTime: 0,
    // Drop the 30s refetch — it competes with the user's active filtering
    // and creates the "first click works, then gets confused" symptom.
    // The connectors tile and sidebar badge each remount on screen
    // visits, which is the natural refresh trigger.
  });
}

export function useCapture(id: string | null) {
  return useQuery({
    queryKey: ['capture', id],
    queryFn: () => get<Capture>(`/v1/captures/${encodeURIComponent(id!)}`),
    enabled: id !== null,
    staleTime: 60_000,
  });
}

export function useMeetings(opts?: { limit?: number }) {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  const query = params.toString();
  return useQuery({
    queryKey: ['meetings', opts ?? {}],
    queryFn: () => get<MeetingsPage>(`/v1/meetings${query ? '?' + query : ''}`),
    staleTime: 60_000,
  });
}

export function useAgenda(date?: string) {
  const today = new Date().toISOString().slice(0, 10);
  const queryDate = date ?? today;
  return useQuery({
    queryKey: ['agenda', queryDate],
    queryFn: () => get<AgendaItem[]>(`/v1/agenda?date=${queryDate}`),
    staleTime: 60_000,
  });
}

export function useRecentActivity(windowMinutes = 240) {
  return useQuery({
    queryKey: ['activity', windowMinutes],
    queryFn: () => get<ActivityRow[]>(`/v1/activity?windowMinutes=${windowMinutes}`),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

export function useActivityHeatmap(days = 365) {
  return useQuery({
    queryKey: ['activity', 'heatmap', days],
    queryFn: () => get<HeatmapResponse>(`/v1/activity/heatmap?days=${days}`),
    staleTime: 60_000,
  });
}

export function useActivityForDate(date: string | null) {
  return useQuery({
    queryKey: ['activity', 'date', date],
    queryFn: () => get<ActivityRow[]>(`/v1/activity?date=${date!}`),
    enabled: !!date,
    staleTime: 60_000,
  });
}

export function useSuggestions() {
  return useQuery({
    queryKey: ['suggestions'],
    queryFn: () => get<Suggestion[]>('/v1/suggestions'),
    staleTime: 5 * 60_000,
  });
}

export function useDaily(opts?: { limit?: number }) {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  const query = params.toString();
  return useQuery({
    queryKey: ['daily', opts ?? {}],
    queryFn: () => get<DailyPage>(`/v1/daily${query ? '?' + query : ''}`),
    staleTime: 60_000,
  });
}

export function useSearch() {
  return useMutation({
    mutationFn: (vars: { q: string; limit?: number }) =>
      post<SearchResponse>('/v1/search', { q: vars.q, limit: vars.limit ?? 10 }),
  });
}

export function useNote(path: string | null) {
  return useQuery({
    queryKey: ['note', path],
    queryFn: () => get<Note>(`/v1/notes?path=${encodeURIComponent(path!)}`),
    enabled: path !== null,
    staleTime: 60_000,
  });
}

export function useRecorderStatus(opts?: { pollWhile?: 'recording' | 'transcribing' | 'all' }) {
  return useQuery({
    queryKey: ['recorder', 'status'],
    queryFn: () => get<RecorderStatus>('/v1/recorder/status'),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      if (opts?.pollWhile === 'all') return 2_000;
      if (data.phase === 'recording') return opts?.pollWhile === 'transcribing' ? false : 4_000;
      if (data.phase === 'transcribing') return 3_000;
      return false; // idle/done — stop polling
    },
    staleTime: 0,
  });
}

export function useStartRecording() {
  return useMutation({
    mutationFn: (vars: StartRecordingRequest) =>
      post<RecorderStatus>('/v1/recorder/start', vars),
  });
}

export function useStopRecording() {
  return useMutation({
    mutationFn: () => post<RecorderStatus>('/v1/recorder/stop'),
  });
}

export function useClearRecording() {
  return useMutation({
    mutationFn: () => post<RecorderStatus>('/v1/recorder/clear'),
  });
}

export function useRecorderSettings() {
  return useQuery({
    queryKey: ['settings', 'recorder'],
    queryFn: () => get<RecorderSettings>('/v1/settings/recorder'),
    staleTime: 5 * 60_000,
  });
}

export function useUpdateRecorderSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: UpdateRecorderSettings) =>
      post<RecorderSettings>('/v1/settings/recorder', vars),
    onSuccess: (data) => {
      qc.setQueryData(['settings', 'recorder'], data);
    },
  });
}

// ── Scheduler ─────────────────────────────────────────────────────────────

export interface SchedulerJobStatus {
  name: string;
  schedule_label: string;
  last_run_at: number | null;
  last_run_ok: boolean | null;
  last_queued: number;
  last_error: string | null;
  last_error_type: string | null;
  last_skipped_reason: string | null;
  next_run_at: number | null;
  consecutive_failures: number;
  failed_since: number | null;
  running: boolean;
}

export interface SchedulerStatus {
  enabled: boolean;
  jobs: Record<string, SchedulerJobStatus>;
  running?: boolean;
}

export interface SchedulerDiagnostics {
  enabled: boolean;
  active_launchd_plists: string[];
  double_scheduling: boolean;
  ffmpeg_available: boolean;
}

export function useSchedulerStatus(opts?: { intervalMs?: number }) {
  return useQuery({
    queryKey: ['scheduler', 'status'],
    queryFn: () => get<SchedulerStatus>('/v1/scheduler/status'),
    refetchInterval: opts?.intervalMs ?? 15_000,
    staleTime: 5_000,
  });
}

export function useSchedulerDiagnostics() {
  return useQuery({
    queryKey: ['scheduler', 'diagnostics'],
    queryFn: () => get<SchedulerDiagnostics>('/v1/scheduler/diagnostics'),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}

// ── Semantic search index ───────────────────────────────────────────────────

export interface SearchIndexStatus {
  /** ISO8601 of the last index rebuild, or null if never indexed. */
  lastIndexedAt: string | null;
  noteCount: number;
  model: string | null;
  /** A reindex is in flight. */
  running: boolean;
}

export function useSearchIndexStatus() {
  return useQuery({
    queryKey: ['search-index', 'status'],
    queryFn: () => get<SearchIndexStatus>('/v1/search/status'),
    // Poll quickly while a reindex runs so the UI tracks completion; otherwise
    // refresh lazily.
    refetchInterval: (query) => (query.state.data?.running ? 2_000 : 30_000),
    staleTime: 5_000,
  });
}

export function useReindex() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post<{ started: boolean }>('/v1/search/reindex'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['search-index', 'status'] }),
  });
}

export interface ConnectorSyncResult {
  connector: string;
  ok: boolean;
  queued: number;
  error: string | null;
  skipped_reason: string | null;
}

export function useSyncConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => post<ConnectorSyncResult>(`/v1/connectors/${id}/sync`),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['connectors'] });
      qc.invalidateQueries({ queryKey: ['scheduler', 'status'] });
    },
  });
}

export function useSyncAllConnectors() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post<Record<string, ConnectorSyncResult>>('/v1/connectors/sync-all'),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['connectors'] });
      qc.invalidateQueries({ queryKey: ['scheduler', 'status'] });
    },
  });
}

export function useMeetingPrep(eventId: string | null) {
  return useQuery({
    queryKey: ['meeting-prep', eventId],
    queryFn: () => get<Prep>(`/v1/meetings/prep/${encodeURIComponent(eventId!)}`),
    enabled: eventId !== null,
    // The brief is cached on the sidecar side and only regenerates when the
    // underlying event changes — no benefit to refetching client-side.
    staleTime: Infinity,
  });
}

export function usePrewarmMeetingPrep() {
  return useMutation({
    mutationFn: (eventId: string) =>
      post<{ status: string }>(
        `/v1/meetings/prep/${encodeURIComponent(eventId)}/prewarm`,
      ),
  });
}

// ── Chat ──────────────────────────────────────────────────────────────────

export function useConversations() {
  return useQuery({
    queryKey: ['chat'],
    queryFn: () => get<ConversationSummary[]>('/v1/chat'),
    staleTime: 10_000,
  });
}

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: ['chat', id],
    queryFn: () => get<Conversation>(`/v1/chat/${encodeURIComponent(id!)}`),
    enabled: id !== null,
    // Refetched explicitly when a turn completes — no background polling.
    staleTime: Infinity,
  });
}

export function useCreateConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post<Conversation>('/v1/chat'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat'] }),
  });
}

export function useRenameConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; title: string }) =>
      patch<Conversation>(`/v1/chat/${encodeURIComponent(vars.id)}`, {
        title: vars.title,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat'] }),
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => del<{ ok: boolean }>(`/v1/chat/${encodeURIComponent(id)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat'] }),
  });
}

// ── Jots ──────────────────────────────────────────────────────────────────

const JOTS_KEY = ['jots'] as const;

export function useJots(params: { q?: string; context?: string; tag?: string; project?: string } = {}) {
  return useQuery({
    queryKey: [...JOTS_KEY, params],
    queryFn: async () => {
      const search = new URLSearchParams({ source: 'manual' });
      if (params.q) search.set('q', params.q);
      if (params.context) search.set('context', params.context);
      if (params.tag) search.set('tag', params.tag);
      if (params.project) search.set('project', params.project);
      return get<JotsPage>(`/v1/notes?${search.toString()}`);
    },
    refetchInterval: 5000,  // pick up overlay-captured jots
  });
}

export function useJot(path: string | null) {
  return useQuery({
    queryKey: ['note-by-path', path],
    queryFn: () => get<Note>(`/v1/notes?path=${encodeURIComponent(path!)}`),
    enabled: !!path,
  });
}

export function useCreateJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: CreateJotRequest) =>
      post<CreateJotResponse>('/v1/notes', req),
    onSuccess: () => qc.invalidateQueries({ queryKey: JOTS_KEY }),
  });
}

export function useUpdateJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; body: string }) =>
      patch<{ id: string; path: string; updated: string }>(
        `/v1/notes/${encodeURIComponent(vars.id)}`,
        { body: vars.body },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: JOTS_KEY });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
    },
  });
}

export function useRouteJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; context: string; project?: string | null }) =>
      post<{ id: string; path: string; context: string }>(
        `/v1/notes/${encodeURIComponent(vars.id)}/route`,
        { context: vars.context, project: vars.project ?? undefined },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: JOTS_KEY });
      // Routing moves the file — the open detail view's path is now stale.
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
    },
  });
}

export function useAutoRouteJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      post<AutoRouteResponse>(`/v1/notes/${encodeURIComponent(id)}/route-auto`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: JOTS_KEY });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
    },
  });
}

export function useExtractPhoto() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jotId, assetPath }: { jotId: string; assetPath: string }) =>
      post<ExtractPhotoResponse>(`/v1/notes/${encodeURIComponent(jotId)}/extract-photo`, { assetPath }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: JOTS_KEY });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
    },
  });
}

export function useDeleteJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => del(`/v1/notes/${encodeURIComponent(id)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: JOTS_KEY }),
  });
}

export function useUpdateNoteByPath() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: UpdateNoteBodyRequest) =>
      patch<UpdateNoteBodyResponse>('/v1/notes/body', vars),
    onSuccess: () => {
      // Both caches read GET /v1/notes?path= — ['note'] (useNote/NoteView)
      // and ['note-by-path'] (useJot/jots screen).
      qc.invalidateQueries({ queryKey: ['note'] });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
    },
  });
}

export function useExportConfluence() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: ConfluenceExportRequest) =>
      post<ConfluenceExportResponse>('/v1/docs/export/confluence', req),
    onSuccess: () => {
      // Export writes frontmatter back to the jot file — invalidate both caches.
      qc.invalidateQueries({ queryKey: JOTS_KEY });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
    },
  });
}

// ── Confluence space list (shared with the Confluence export dialog) ──

export function useImportSpaces() {
  return useQuery({
    queryKey: ['import', 'spaces'],
    queryFn: () => get<ImportSpace[]>('/v1/import/confluence/spaces'),
    staleTime: 5 * 60_000,
    // A 409 (connector not configured) must render the call-to-action
    // immediately — never spin through React Query's default 3 retries.
    retry: false,
  });
}

// ── Projects ──────────────────────────────────────────────────────────────

export function useProjects(opts?: { includeArchived?: boolean }) {
  return useQuery({
    queryKey: ['projects', opts ?? {}],
    queryFn: () =>
      get<Project[]>(`/v1/projects${opts?.includeArchived ? '?includeArchived=true' : ''}`),
    staleTime: 30_000,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: CreateProjectRequest) => post<Project>('/v1/projects', req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  });
}

export function useUpdateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { context: string; slug: string } & UpdateProjectRequest) =>
      patch<Project>(`/v1/projects/${vars.context}/${vars.slug}`, {
        name: vars.name,
        description: vars.description,
        archived: vars.archived,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  });
}

// ── Connector Auth Sessions ───────────────────────────────────────────────────

export function useStartAuth() {
  return useMutation({
    mutationFn: (a: { id: string; params?: Record<string, unknown> }) =>
      post<AuthSessionView>(`/v1/connectors/${a.id}/auth/start`, { params: a.params ?? {} }),
  });
}

export function useSubmitAuth() {
  return useMutation({
    mutationFn: (a: { id: string; sessionId: string; data: Record<string, unknown> }) =>
      post<AuthSessionView>(`/v1/connectors/${a.id}/auth/submit`, { session_id: a.sessionId, data: a.data }),
  });
}

export function useAuthStatus(id: string | null, sessionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['auth-status', id, sessionId],
    queryFn: () => get<AuthSessionView>(`/v1/connectors/${id}/auth/status?session_id=${sessionId}`),
    enabled: enabled && id !== null && sessionId !== null,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === 'pending' || s === 'waiting_input' ? 2000 : false;
    },
  });
}

export function useCancelAuth() {
  return useMutation({
    mutationFn: (a: { id: string; sessionId: string }) =>
      post(`/v1/connectors/${a.id}/auth/cancel`, { session_id: a.sessionId }),
  });
}

export function useDisconnectConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: { id: string; account?: string }) =>
      del(`/v1/connectors/${a.id}/credentials${a.account ? `?account=${encodeURIComponent(a.account)}` : ''}`),
    onSettled: () => qc.invalidateQueries({ queryKey: ['connectors'] }),
  });
}


export function useMcpServers() {
  return useQuery({
    queryKey: ['chat', 'mcp-servers'],
    queryFn: () => get<McpServersResponse>('/v1/chat/mcp-servers'),
    staleTime: 30_000,
  });
}

export function useSaveMcpServers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (servers: McpServerWrite[]) =>
      put<{ servers: McpServersResponse['servers'] }>('/v1/chat/mcp-servers', { servers }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['chat', 'mcp-servers'] }),
  });
}
