// TypeScript mirrors of the Pydantic models in ghostbrain/api/models/.
// Kept in sync manually for Phase 1; consider OpenAPI codegen in Phase 2.

export interface VaultStats {
  totalNotes: number;
  queuePending: number;
  vaultSizeBytes: number;
  lastSyncAt: string | null;
  indexedCount: number;
}

export type ConnectorState = 'on' | 'off' | 'err';

export interface Connector {
  id: string;
  displayName: string;
  state: ConnectorState;
  count: number;
  lastSyncAt: string | null;
  account: string | null;
  throughput: string | null;
  error: string | null;
}

export interface ConnectorDetail extends Connector {
  scopes: string[];
  pulls: string[];
  vaultDestination: string;
}

export interface CaptureSummary {
  id: string;
  source: string;
  title: string;
  snippet: string;
  from: string;
  tags: string[];
  unread: boolean;
  capturedAt: string;
  path: string | null;
}

export interface Capture extends CaptureSummary {
  body: string;
  extracted: Record<string, unknown> | null;
  sourceUrl: string | null;
}

export interface CapturesPage {
  total: number;
  items: CaptureSummary[];
}

export interface PastMeeting {
  id: string;
  title: string;
  date: string;
  dur: string;
  speakers: number;
  tags: string[];
  path: string | null;
}

export interface MeetingsPage {
  total: number;
  items: PastMeeting[];
}

export type AgendaStatus = 'upcoming' | 'recorded';

export interface AgendaItem {
  id: string;
  time: string;
  duration: string;
  title: string;
  with: string[];
  status: AgendaStatus;
}

export interface ActivityRow {
  id: string;
  source: string;
  verb: string;
  subject: string;
  atRelative: string;
  at: string;
  path: string | null;
}

export interface HeatmapDay {
  date: string; // YYYY-MM-DD
  count: number;
  bySource: Record<string, number>;
}

export interface HeatmapResponse {
  days: HeatmapDay[];
  total: number;
  maxCount: number;
}

export interface Suggestion {
  id: string;
  icon: string;
  title: string;
  body: string;
  accent: boolean;
}

export interface DailyDigest {
  id: string;
  date: string;
  title: string;
  snippet: string;
  noteCount: number;
}

export interface DailyPage {
  total: number;
  items: DailyDigest[];
}

export interface SearchHit {
  path: string;
  title: string;
  snippet: string;
  score: number;
}

export interface SearchResponse {
  query: string;
  total: number;
  items: SearchHit[];
}

export interface AnswerRequest {
  q: string;
  limit?: number;
}

export interface AnswerResponse {
  query: string;
  answer: string;
  sources: SearchHit[];
  error: string | null;
}

export interface Note {
  path: string;
  title: string;
  body: string;
  frontmatter: Record<string, unknown>;
}

export interface UpdateNoteBodyRequest {
  path: string;
  body: string;
}

export interface UpdateNoteBodyResponse {
  path: string;
  updated: string | null;
}

export type RecorderPhase = 'idle' | 'recording' | 'transcribing' | 'done';
export type RecorderOwner = 'manual' | 'daemon';

export interface RecorderStatus {
  phase: RecorderPhase;
  owner: RecorderOwner | null;
  title: string | null;
  startedAt: string | null;
  wavPath: string | null;
  transcriptPath: string | null;
  error: string | null;
}

export interface StartRecordingRequest {
  title?: string;
  context?: string;
}

export interface RecorderSettings {
  enabled: boolean;
  excluded_titles: string[];
  manual_context: string;
}

export interface UpdateRecorderSettings {
  enabled?: boolean;
  excluded_titles?: string[];
  manual_context?: string;
}

export interface EventSnapshot {
  title: string;
  start: string;
  end: string;
  with: string[];
  location: string;
  description: string;
  hash: string;
}

export interface RelatedItem {
  path: string;
  title: string;
  source: string;  // "calendar" | "meeting" | "email" | "slack" | "jira" | …
  snippet: string;
  score: number;
}

export interface Prep {
  eventId: string;
  brief: string | null;
  related: RelatedItem[];
  eventSnapshot: EventSnapshot;
  generatedAt: string;
  error: string | null;
}

// ── Chat ──────────────────────────────────────────────────────────────────

export interface ChatToolUse {
  name: string;
  summary: string;
}

export interface ChatAttachment {
  path: string;
  title: string;
  kind: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  tools?: ChatToolUse[];
  interrupted?: boolean;
  attachments?: ChatAttachment[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  claude_session_id: string | null;
  messages: ChatMessage[];
}

/** Mirrors the event vocabulary of ghostbrain/llm/agent.py. */
export type ChatStreamEvent =
  | { type: 'session'; session_id: string }
  | { type: 'delta'; text: string }
  | { type: 'tool'; name: string; summary: string }
  | { type: 'done'; text: string; session_id?: string }
  | { type: 'error'; message: string; interrupted?: boolean };
// ── Docs assist ───────────────────────────────────────────────────────────

/** Mirrors the event vocabulary of the /v1/docs/assist SSE endpoint —
 *  same shape as chat events so the same renderer logic handles both. */
export type DocsAssistEvent = ChatStreamEvent;

export type DocsAssistMode = 'draft' | 'polish' | 'expand' | 'summarize';

export interface DocsAssistRequest {
  jot_id: string;
  mode: DocsAssistMode;
  instruction?: string;
  selection?: string;
}

export interface ConfluenceExportRequest {
  jot_id: string;
  space_key: string;
  parent_id?: string;
  title?: string;
  force_new?: boolean;
}

export interface ConfluenceExportResponse {
  action: 'created' | 'updated';
  page_id: string;
  url: string;
}

// ── Jots ──────────────────────────────────────────────────────────────────

export type JotRoutingStatus = 'pending' | 'routed' | 'manual_review';

export interface JotListItem {
  id: string;
  path: string;
  title: string;
  excerpt: string;
  context: string | null;
  routingStatus: JotRoutingStatus;
  tags: string[];
  created: string;
  updated: string;
  project?: string | null;
  thumbnail?: string | null;
}

export interface JotsPage {
  items: JotListItem[];
  total: number;
}

export interface CreateJotRequest {
  body: string;
  capturedAt?: string;
  route?: boolean;  // omit or true = route on create; false = stay pending
}

export interface CreateJotResponse {
  id: string;
  path: string;
  routingStatus: JotRoutingStatus;
}

export interface AutoRouteResponse {
  id: string;
  path: string;
  routingStatus: JotRoutingStatus;
  context?: string | null;
}

export interface ExtractPhotoResponse {
  id: string;
  path: string;
  body: string;
  extracted: boolean;
  reason?: string;
}

// ── Confluence space list (shared with the Confluence export dialog) ──

export interface ImportSpace {
  site: string;
  siteSlug: string;
  key: string;
  name: string;
  context: string;
}

// ── Projects ──────────────────────────────────────────────────────────────

export interface Project {
  id: string;
  context: string;
  slug: string;
  name: string;
  description: string;
  archived: boolean;
  created_at: number;
}

export interface CreateProjectRequest {
  context: string;
  name: string;
  description?: string;
}

export interface UpdateProjectRequest {
  name?: string;
  description?: string;
  archived?: boolean;
}

export interface ChatExportResponse {
  jot_id: string;
  path: string;
  routingStatus: string;
  context: string | null;
  project: string | null;
  title: string;
}

// ── Brain Constellation ───────────────────────────────────────────────────────

export interface VaultGraphNode {
  path: string;
  title: string;
  context: string;
  tags: string[];
  x: number;
  y: number;
  degree: number;
  updated: string | null;
}

export interface VaultGraphEdge {
  source: string;
  target: string;
  weight: number;
  kind: 'related' | 'wikilink';
}

export interface VaultGraphRegion {
  id: string;
  label: string;
  color: string;
  count: number;
}

export interface VaultGraph {
  nodes: VaultGraphNode[];
  edges: VaultGraphEdge[];
  regions: VaultGraphRegion[];
}
