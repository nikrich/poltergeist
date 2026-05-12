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
