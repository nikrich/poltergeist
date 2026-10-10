import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import type {
  DocDetail,
  DocFolderNode,
  DocSummary,
  FolderRef,
  LibraryTree,
  UploadDocRequest,
  UploadDocResponse,
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
  BackfillState,
  BacklinksResponse,
  Connector,
  ConnectorDetail,
  Conversation,
  ConversationSummary,
  CreateJotRequest,
  CreateJotResponse,
  CreateProjectRequest,
  DailyPage,
  HeatmapResponse,
  HistoryBlobResponse,
  JotsPage,
  LlmProvidersResponse,
  LlmSettings,
  MeetingsPage,
  Note,
  NoteHistoryResponse,
  Prep,
  Project,
  CaptureHelperDiagnostics,
  RestoreHistoryResponse,
  RecorderSettings,
  RecorderStatus,
  SearchResponse,
  SetCaptureTargetRequest,
  StartRecordingRequest,
  Suggestion,
  UpdateLlmSettings,
  UpdateNoteBodyRequest,
  UpdateNoteBodyResponse,
  UpdateJotResponse,
  UpdateProjectRequest,
  UpdateRecorderSettings,
  VaultGraph,
  EgoGraph,
  VaultContexts,
  WhatsAppChat,
  VaultStats,
  McpServersResponse,
  McpServerWrite,
  TemplateCreateResponse,
  TemplateRenderResponse,
  TemplatesResponse,
} from '../../../shared/api-types';
import { ApiError, del, get, patch, post, put } from './client';
import { reportHistoryHealth } from '../history-health';

export function useVaultStats() {
  return useQuery({
    queryKey: ['vault', 'stats'],
    queryFn: () => get<VaultStats>('/v1/vault/stats'),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

export function useContexts() {
  return useQuery({
    queryKey: ['vault', 'contexts'],
    queryFn: () => get<VaultContexts>('/v1/vault/contexts'),
    staleTime: 60_000,
  });
}

function invalidateContexts(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ['vault', 'contexts'] });
  qc.invalidateQueries({ queryKey: ['connectors'] });
  qc.invalidateQueries({ queryKey: ['connector'] });
  qc.invalidateQueries({ queryKey: ['projects'] });
}

export function useCreateContext() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => post<VaultContexts>('/v1/vault/contexts', { name }),
    onSuccess: () => invalidateContexts(qc),
  });
}

export function useArchiveContext() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      del<VaultContexts>('/v1/vault/contexts/' + encodeURIComponent(name)),
    onSuccess: () => invalidateContexts(qc),
  });
}

export function useVaultGraph(opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ['vault', 'graph'],
    queryFn: () => get<VaultGraph>('/v1/vault/graph'),
    staleTime: 60_000,
    enabled: opts.enabled ?? true,
  });
}

/** Link neighbourhood of `focus` (A6). Keeps the previous graph on screen
 * while a recentre loads; polls while the sidecar's link index is cold. */
export function useEgoGraph(focus: string | null, depth: number) {
  return useQuery({
    queryKey: ['vault', 'graph', 'ego', focus, depth],
    queryFn: () =>
      get<EgoGraph>(`/v1/vault/graph?focus=${encodeURIComponent(focus!)}&depth=${depth}`),
    enabled: focus !== null,
    staleTime: 10_000,
    placeholderData: keepPreviousData,
    refetchInterval: (query) => (query.state.data?.indexing ? 3_000 : false),
  });
}

export function useBacklinks(path: string | null) {
  return useQuery({
    queryKey: ['vault', 'backlinks', path],
    queryFn: () =>
      get<BacklinksResponse>(`/v1/vault/backlinks?path=${encodeURIComponent(path!)}`),
    enabled: path !== null,
    staleTime: 5_000,
    // Cold link index on the sidecar: poll until it's built.
    refetchInterval: (query) => (query.state.data?.indexing ? 3_000 : false),
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
      // idle/done: keep a slow poll. The calendar-driven daemon starts
      // recordings on its own; with polling off the UI stayed on the lobby
      // while a recording ran and "record" answered 409 "in progress".
      return opts?.pollWhile === 'transcribing' ? false : 15_000;
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

/** Answer the native helper's "no meeting window found" prompt. 409 if idle. */
export function useSetCaptureTarget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: SetCaptureTargetRequest) =>
      post<RecorderStatus>('/v1/recorder/capture/target', vars),
    onSuccess: (data) => {
      qc.setQueryData(['recorder', 'status'], data);
    },
  });
}

/**
 * Trigger the macOS Screen Recording / Microphone permission prompts via the
 * native helper. Blocks until the user answers (up to ~60 s), then hands back
 * the fresh probe which is written straight into the diagnostics cache.
 */
export function useRequestCapturePermissions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const helper = await post<CaptureHelperDiagnostics>(
        '/v1/recorder/capture/request-permissions',
      );
      qc.setQueryData<SchedulerDiagnostics>(['scheduler', 'diagnostics'], (prev) =>
        prev ? { ...prev, capture_helper: helper } : prev,
      );
      // Re-probe with refresh=1 rather than a plain invalidate: a normal GET
      // could hand back the sidecar's 60 s cached probe and undo the update.
      try {
        const diagnostics = await get<SchedulerDiagnostics>(
          '/v1/scheduler/diagnostics?refresh=1',
        );
        qc.setQueryData(['scheduler', 'diagnostics'], diagnostics);
      } catch {
        // best-effort — the helper result above is already in the cache
      }
      void qc.invalidateQueries({ queryKey: ['settings', 'recorder'] });
      return helper;
    },
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
  platform: string;
  /** Resolved capture backend ("native" | "blackhole" | "wasapi" | "unsupported"). */
  effective_backend: string;
  /** Native helper probe; null off macOS. */
  capture_helper: CaptureHelperDiagnostics | null;
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

/**
 * Re-probe the capture helper, bypassing the sidecar's 60 s probe cache
 * (`?refresh=1`), and write the result into the diagnostics query cache.
 * Also refreshes recorder settings since `capture_backend_effective` may move.
 */
export function useRefreshSchedulerDiagnostics() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => get<SchedulerDiagnostics>('/v1/scheduler/diagnostics?refresh=1'),
    onSuccess: (data) => {
      qc.setQueryData(['scheduler', 'diagnostics'], data);
      void qc.invalidateQueries({ queryKey: ['settings', 'recorder'] });
    },
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

export function useUpdateConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; title?: string; project?: string | null }) => {
      const body: Record<string, unknown> = {};
      if (vars.title !== undefined) body.title = vars.title;
      if (vars.project !== undefined) body.project = vars.project;
      return patch<Conversation>(`/v1/chat/${encodeURIComponent(vars.id)}`, body);
    },
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
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: JOTS_KEY }),
        qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] }),
      ]),
  });
}

export function useUpdateJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; body: string; ifMatch?: string | null }) =>
      patch<UpdateJotResponse>(
        `/v1/notes/${encodeURIComponent(vars.id)}`,
        { body: vars.body },
        { ifMatch: vars.ifMatch },
      ),
    onSuccess: (res) => {
      reportHistoryHealth(res);
      qc.invalidateQueries({ queryKey: JOTS_KEY });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
      qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] });
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
      qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] });
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
      qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] });
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
      qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] });
    },
  });
}

export function useDeleteJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => del(`/v1/notes/${encodeURIComponent(id)}`),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: JOTS_KEY }),
        qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] }),
      ]),
  });
}

export function useUpdateNoteByPath() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: UpdateNoteBodyRequest & { ifMatch?: string | null }) =>
      patch<UpdateNoteBodyResponse>(
        '/v1/notes/body',
        { path: vars.path, body: vars.body },
        { ifMatch: vars.ifMatch },
      ),
    onSuccess: (res) => {
      reportHistoryHealth(res);
      // Both caches read GET /v1/notes?path= — ['note'] (useNote/NoteView)
      // and ['note-by-path'] (useJot/jots screen).
      qc.invalidateQueries({ queryKey: ['note'] });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
      qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] });
    },
  });
}

export function useNoteHistory(path: string | null) {
  return useQuery({
    queryKey: ['note-history', path],
    queryFn: () =>
      get<NoteHistoryResponse>(`/v1/notes/history?path=${encodeURIComponent(path!)}`),
    enabled: path !== null,
    staleTime: 0,
  });
}

export function useHistoryVersion(path: string | null, blob: string | null) {
  return useQuery({
    queryKey: ['note-history', path, blob],
    queryFn: () =>
      get<HistoryBlobResponse>(
        `/v1/notes/history/blob?path=${encodeURIComponent(path!)}&blob=${encodeURIComponent(blob!)}`,
      ),
    enabled: path !== null && blob !== null,
    staleTime: 0,
  });
}

export function useRestoreVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { path: string; blob: string }) =>
      post<RestoreHistoryResponse>('/v1/notes/history/restore', vars),
    onSuccess: (res) => {
      reportHistoryHealth(res);
      qc.invalidateQueries({ queryKey: ['note-history'] });
      qc.invalidateQueries({ queryKey: ['note'] });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
      qc.invalidateQueries({ queryKey: JOTS_KEY });
      qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] });
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
    // A rename moves the project's folder, re-stamps its notes and rewrites
    // chat/jot/library paths, so every surface that lists them is stale —
    // page history too (it follows the moved notes to their new paths).
    onSuccess: () =>
      Promise.all(
        [
          ['projects'],
          ['library'],
          ['jots'],
          ['note'],
          ['note-by-path'],
          ['note-history'],
          ['vault'],
          ['chat'],
        ].map(
          (queryKey) => qc.invalidateQueries({ queryKey }),
        ),
      ),
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

export function useUpdateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: {
      connectorId: string;
      accountId: string;
      context?: string | null;
      enabled?: boolean;
    }) => {
      const body: { context?: string | null; enabled?: boolean } = {};
      if (a.context !== undefined) body.context = a.context;
      if (a.enabled !== undefined) body.enabled = a.enabled;
      return patch(
        `/v1/connectors/${a.connectorId}/accounts/${encodeURIComponent(a.accountId)}`,
        body,
      );
    },
    onSettled: (_data, _err, a) => {
      qc.invalidateQueries({ queryKey: ['connector', a.connectorId] });
      qc.invalidateQueries({ queryKey: ['connectors'] });
    },
  });
}

const backfillPath = (connectorId: string, accountId: string) =>
  `/v1/connectors/${connectorId}/accounts/${encodeURIComponent(accountId)}/backfill`;

/** Backfill state for one account of a given connector; `null` when none exists (404).
 * Polls every 15 s only while the job is running. Shared by Gmail and Drive. */
export function useAccountBackfill(connectorId: string, accountId: string, enabled = true) {
  return useQuery({
    queryKey: ['backfill', connectorId, accountId],
    queryFn: async ({ signal }) => {
      try {
        return await get<BackfillState>(backfillPath(connectorId, accountId), { signal });
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
    enabled,
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 15_000 : false),
  });
}

export function useBackfillEstimate<T>(
  connectorId: string,
  accountId: string,
  years: number,
  enabled = true,
) {
  return useQuery({
    queryKey: ['backfill-estimate', connectorId, accountId, years],
    queryFn: ({ signal }) =>
      get<T>(`${backfillPath(connectorId, accountId)}/estimate?years=${years}`, { signal }),
    enabled,
    retry: false,
    staleTime: 5 * 60_000,
  });
}

export function useStartBackfill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: { connectorId: string; accountId: string; years: number }) =>
      post<BackfillState>(backfillPath(a.connectorId, a.accountId), { years: a.years }),
    onSettled: (_data, _err, a) =>
      qc.invalidateQueries({ queryKey: ['backfill', a.connectorId, a.accountId] }),
  });
}

export type BackfillAction = 'pause' | 'resume' | 'cancel';

export function useBackfillAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: { connectorId: string; accountId: string; action: BackfillAction }) =>
      a.action === 'cancel'
        ? del(backfillPath(a.connectorId, a.accountId))
        : post(`${backfillPath(a.connectorId, a.accountId)}/${a.action}`),
    onSettled: (_data, _err, a) =>
      qc.invalidateQueries({ queryKey: ['backfill', a.connectorId, a.accountId] }),
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

// ── LLM providers ────────────────────────────────────────────────────────

export function useLlmSettings() {
  return useQuery({
    queryKey: ['settings', 'llm'],
    queryFn: () => get<LlmSettings>('/v1/settings/llm'),
    staleTime: 5 * 60_000,
  });
}

export function useUpdateLlmSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: UpdateLlmSettings) => put<LlmSettings>('/v1/settings/llm', vars),
    onSuccess: (data) => {
      qc.setQueryData(['settings', 'llm'], data);
      // A provider (or model) change can flip which provider is "active" and
      // invalidates the cached diagnostics probe — re-run it so the panel
      // doesn't keep showing the previous provider's health.
      void qc.invalidateQueries({ queryKey: ['llm', 'providers'] });
    },
  });
}

/** Probes each provider CLI/HTTP endpoint — can take a few seconds, so this
 * is cached for a while and only re-run on an explicit "re-check". */
export function useLlmProviders() {
  return useQuery({
    queryKey: ['llm', 'providers'],
    queryFn: () => get<LlmProvidersResponse>('/v1/llm/providers'),
    staleTime: 30_000,
  });
}

/** The "re-check" button. `refresh=1` bypasses the sidecar's 60s probe cache,
 * which a plain refetch would otherwise be served from — the whole point of
 * the button is to see the state *after* installing or signing into a CLI. */
export function useRecheckLlmProviders() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => get<LlmProvidersResponse>('/v1/llm/providers?refresh=1'),
    onSuccess: (data) => qc.setQueryData(['llm', 'providers'], data),
  });
}

export function useWhatsAppChats(enabled = true) {
  return useQuery({
    queryKey: ['whatsapp', 'chats'],
    queryFn: () => get<WhatsAppChat[]>('/v1/connectors/whatsapp/chats'),
    enabled,
    retry: false,
    staleTime: 60_000,
  });
}

export function useSaveWhatsAppChats() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (chats: Record<string, { allowed: boolean; context: string | null }>) =>
      put<WhatsAppChat[]>('/v1/connectors/whatsapp/chats', { chats }),
    onSuccess: (data) => {
      qc.setQueryData(['whatsapp', 'chats'], data);
      qc.invalidateQueries({ queryKey: ['connectors'] });
      qc.invalidateQueries({ queryKey: ['connector', 'whatsapp'] });
    },
  });
}

// ── Docs library ─────────────────────────────────────────────────────────────

const invalidateLibrary = (qc: ReturnType<typeof useQueryClient>) =>
  qc.invalidateQueries({ queryKey: ['library'] });

function anyPending(tree: LibraryTree | undefined): boolean {
  if (!tree) return false;
  const walk = (n: { docs: DocSummary[]; folders: DocFolderNode[] }): boolean =>
    n.docs.some((d) => d.summary_state === 'pending' || d.index_status === 'pending') || n.folders.some(walk);
  return tree.scopes.some(walk);
}

export function useLibraryTree() {
  return useQuery({
    queryKey: ['library', 'tree'],
    queryFn: () => get<LibraryTree>('/v1/library/tree'),
    staleTime: 5_000,
    refetchInterval: (q) => (anyPending(q.state.data as LibraryTree | undefined) ? 3_000 : false),
  });
}

export function useSummariseDoc() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => post<{ queued: boolean }>(`/v1/library/docs/${docId}/summarise`),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useDocDetail(docId: string | null) {
  return useQuery({
    queryKey: ['library', 'doc', docId],
    queryFn: () => get<DocDetail>(`/v1/library/docs/${docId}`),
    enabled: !!docId,
  });
}

export function useLibrarySearch(q: string, project?: string | null) {
  const params = new URLSearchParams({ q });
  if (project) params.set('project', project);
  return useQuery({
    queryKey: ['library', 'search', q, project ?? null],
    queryFn: () => get<DocSummary[]>(`/v1/library/search?${params.toString()}`),
    enabled: q.trim().length > 0,
    staleTime: 5_000,
  });
}

export function useUploadDoc() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: UploadDocRequest) => post<UploadDocResponse>('/v1/library/docs', req),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function usePatchDoc() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ docId, ...body }: { docId: string; title?: string; context?: string; project?: string | null; folder?: string }) =>
      patch<DocSummary>(`/v1/library/docs/${docId}`, body),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useDeleteDoc() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => del(`/v1/library/docs/${docId}`),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useReindexDoc() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => post<DocSummary>(`/v1/library/docs/${docId}/reindex`),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useCreateFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ref: FolderRef) => post<FolderRef>('/v1/library/folders', ref),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useMoveFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { from: FolderRef; to: FolderRef }) => patch<FolderRef>('/v1/library/folders', vars),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useDeleteFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ref: FolderRef) => {
      const params = new URLSearchParams({ context: ref.context, path: ref.path });
      if (ref.project) params.set('project', ref.project);
      return del(`/v1/library/folders?${params.toString()}`);
    },
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useAdoptOriginal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { context: string; project: string | null; folder: string; name: string }) =>
      post<DocSummary>('/v1/library/attention/adopt', vars),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useRemoveOrphan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => post('/v1/library/attention/remove-orphan', { doc_id: docId }),
    onSuccess: () => invalidateLibrary(qc),
  });
}

// ── Smart templates (C1) ──────────────────────────────────────────────────

export function useTemplates(opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ['templates'],
    queryFn: () => get<TemplatesResponse>('/v1/templates'),
    enabled: opts.enabled ?? true,
    staleTime: 10_000,
  });
}

export interface TemplateAnswersVars {
  id: string;
  answers: Record<string, string>;
}

export function useCreateFromTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, answers }: TemplateAnswersVars) =>
      post<TemplateCreateResponse>(`/v1/templates/${encodeURIComponent(id)}/create`, { answers }),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: JOTS_KEY }),
        qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] }),
      ]),
  });
}

export function useRenderTemplate() {
  return useMutation({
    mutationFn: ({ id, answers }: TemplateAnswersVars) =>
      post<TemplateRenderResponse>(`/v1/templates/${encodeURIComponent(id)}/render`, { answers }),
  });
}
