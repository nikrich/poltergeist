// Demo-mode fixtures — entirely fictional data served when GHOSTBRAIN_DEMO=1.
//
// This file exists so a showcase video can be recorded against the real UI
// without spawning the Python sidecar and without exposing any of the user's
// actual vault, mail, calendar, or connector data. Every name, company,
// project, and message below is invented. Nothing here reads from disk or the
// network.
//
// The handler mirrors the response envelope of ../api-forwarder.ts
// (`{ ok: true, data }` / `{ ok: false, error, status }`) so the renderer's
// api client treats it identically to a live backend.

import type { ApiResult } from '../api-forwarder';
import type {
  ActivityRow,
  AgendaItem,
  Capture,
  CapturesPage,
  CaptureSummary,
  Connector,
  ConnectorDetail,
  Conversation,
  ConversationSummary,
  DailyPage,
  HeatmapResponse,
  JotListItem,
  JotsPage,
  MeetingsPage,
  Note,
  RecorderSettings,
  RecorderStatus,
  Suggestion,
  VaultStats,
} from '../../shared/api-types';

// Scheduler shapes are owned by the renderer's hooks module; mirrored here as
// plain objects (served over IPC as data, so only the runtime shape matters).

const now = () => Date.now();
const minsAgo = (m: number) => new Date(now() - m * 60_000).toISOString();
const isoDay = (offsetDays: number) =>
  new Date(now() - offsetDays * 86_400_000).toISOString().slice(0, 10);

// ── Connectors ──────────────────────────────────────────────────────────────
// `id` matches an SVG under renderer/public/assets/connectors. State mix gives
// the connectors screen something to show (live, error, off).

const CONNECTORS: Connector[] = [
  { id: 'gmail', displayName: 'Gmail', state: 'on', count: 4127, lastSyncAt: minsAgo(3), account: 'you@northwind.io', throughput: '~120/day', error: null },
  { id: 'slack', displayName: 'Slack', state: 'on', count: 8810, lastSyncAt: minsAgo(1), account: 'Northwind HQ', throughput: '~400/day', error: null },
  { id: 'calendar', displayName: 'Calendar', state: 'on', count: 642, lastSyncAt: minsAgo(6), account: 'you@northwind.io', throughput: '~8/day', error: null },
  { id: 'jira', displayName: 'Jira', state: 'on', count: 1356, lastSyncAt: minsAgo(11), account: 'northwind.atlassian.net', throughput: '~30/day', error: null },
  { id: 'github', displayName: 'GitHub', state: 'on', count: 2980, lastSyncAt: minsAgo(2), account: 'northwind-labs', throughput: '~90/day', error: null },
  { id: 'confluence', displayName: 'Confluence', state: 'on', count: 511, lastSyncAt: minsAgo(24), account: 'northwind.atlassian.net', throughput: '~6/day', error: null },
  { id: 'notion', displayName: 'Notion', state: 'off', count: 0, lastSyncAt: null, account: null, throughput: null, error: null },
  { id: 'linear', displayName: 'Linear', state: 'err', count: 743, lastSyncAt: minsAgo(220), account: 'northwind', throughput: '~20/day', error: 'token expired — reauthorize to resume' },
];

const CONNECTOR_DETAIL: Record<string, Omit<ConnectorDetail, keyof Connector>> = {
  gmail: {
    scopes: ['gmail.readonly', 'gmail.metadata'],
    pulls: ['threads', 'attachments', 'action items'],
    vaultDestination: '~/vault/sources/gmail',
  },
  slack: {
    scopes: ['channels:history', 'groups:history', 'users:read'],
    pulls: ['mentions', 'saved messages', 'threads you joined'],
    vaultDestination: '~/vault/sources/slack',
  },
  calendar: {
    scopes: ['calendar.events.readonly'],
    pulls: ['events', 'attendees', 'meeting notes'],
    vaultDestination: '~/vault/sources/calendar',
  },
  jira: {
    scopes: ['read:jira-work'],
    pulls: ['issues you watch', 'comments', 'status changes'],
    vaultDestination: '~/vault/sources/jira',
  },
  github: {
    scopes: ['repo', 'read:org'],
    pulls: ['PRs', 'reviews', 'issues', 'releases'],
    vaultDestination: '~/vault/sources/github',
  },
  confluence: {
    scopes: ['read:confluence-content.all'],
    pulls: ['pages you edit', 'spaces you watch'],
    vaultDestination: '~/vault/sources/confluence',
  },
  notion: {
    scopes: [],
    pulls: ['pages', 'databases'],
    vaultDestination: '~/vault/sources/notion',
  },
  linear: {
    scopes: ['read'],
    pulls: ['assigned issues', 'comments'],
    vaultDestination: '~/vault/sources/linear',
  },
};

function connectorDetail(id: string): ConnectorDetail | null {
  const base = CONNECTORS.find((c) => c.id === id);
  if (!base) return null;
  const extra = CONNECTOR_DETAIL[id] ?? { scopes: [], pulls: [], vaultDestination: '~/vault' };
  return { ...base, ...extra };
}

// ── Captures (inbox) ─────────────────────────────────────────────────────────

const CAPTURE_BODIES: Record<string, string> = {
  c1: `Maya pulled the launch forward. Quick summary of the thread:\n\n- **New target: Thursday next week** (was the 28th)\n- Marketing needs final copy by Tuesday EOD\n- Diego is blocked on the billing migration — flagged as the one real risk\n\nShe asked us to lock the date in today's standup.`,
  c2: `> can someone confirm the Aurora rollout is behind the \`aurora_v2\` flag? QA wants to smoke-test before we flip it for everyone.\n\nThread has 14 replies — consensus is yes, flag is in place, default off in prod.`,
  c3: `**AUR-142 · Billing migration dry-run**\n\nStatus moved \`In Progress\` → \`In Review\`. Diego attached the dry-run report: 0 failed rows out of 41k. One follow-up: reconcile the 3 legacy currency codes before the real run.`,
  c4: `PR #2208 — *Cut Aurora launch toggle over to LaunchDarkly*\n\nReviewers: you, Priya. CI green. Priya left one comment about naming the flag consistently with the analytics event.`,
  c5: `Priya shared the updated metrics dashboard spec. Adds activation funnel + a "time to first capture" panel. Wants sign-off before she briefs the data team.`,
  c6: `Calendar: **Aurora launch readiness review** moved to 15:00 today, room Helix / Meet. Tom added the SRE on-call as an optional attendee.`,
};

const CAPTURES: CaptureSummary[] = [
  { id: 'c1', source: 'gmail', title: 'Re: Aurora launch — moving the date up', snippet: 'New target is Thursday next week — marketing needs copy by Tuesday.', from: 'Maya Chen', tags: ['aurora', 'launch'], unread: true, capturedAt: minsAgo(12), path: 'sources/gmail/aurora-launch-date.md' },
  { id: 'c2', source: 'slack', title: '#aurora-launch — confirm rollout flag', snippet: 'can someone confirm the rollout is behind aurora_v2?', from: 'Diego Santos', tags: ['aurora'], unread: true, capturedAt: minsAgo(34), path: 'sources/slack/aurora-flag.md' },
  { id: 'c3', source: 'jira', title: 'AUR-142 — Billing migration dry-run', snippet: '0 failed rows out of 41k — one follow-up on currency codes.', from: 'AUR-142', tags: ['billing'], unread: true, capturedAt: minsAgo(58), path: 'sources/jira/AUR-142.md' },
  { id: 'c4', source: 'github', title: 'PR #2208 — flag cutover to LaunchDarkly', snippet: 'CI green · 1 review comment from Priya.', from: 'northwind-labs', tags: ['review'], unread: false, capturedAt: minsAgo(96), path: 'sources/github/pr-2208.md' },
  { id: 'c5', source: 'slack', title: '#design — metrics dashboard spec v2', snippet: 'adds activation funnel + time-to-first-capture panel.', from: 'Priya Nair', tags: ['metrics'], unread: false, capturedAt: minsAgo(140), path: 'sources/slack/dashboard-spec.md' },
  { id: 'c6', source: 'calendar', title: 'Aurora launch readiness review — 15:00', snippet: 'moved to 15:00 today · room Helix / Meet.', from: 'Calendar', tags: ['meeting'], unread: false, capturedAt: minsAgo(180), path: 'sources/calendar/readiness-review.md' },
  { id: 'c7', source: 'gmail', title: 'Weekly digest — Northwind Labs', snippet: '6 releases shipped, 2 incidents resolved, 1 postmortem filed.', from: 'digest@northwind.io', tags: ['digest'], unread: false, capturedAt: minsAgo(300), path: 'sources/gmail/weekly-digest.md' },
  { id: 'c8', source: 'github', title: 'Release v2.4.0 — Helix', snippet: 'tagged and published · changelog attached.', from: 'northwind-labs', tags: ['release'], unread: false, capturedAt: minsAgo(420), path: 'sources/github/helix-2-4-0.md' },
];

function captureDetail(id: string): Capture | null {
  const s = CAPTURES.find((c) => c.id === id);
  if (!s) return null;
  return {
    ...s,
    body: CAPTURE_BODIES[id] ?? s.snippet,
    extracted: null,
    sourceUrl: null,
  };
}

// ── Today: agenda, activity, suggestions, vault stats ────────────────────────

const AGENDA: AgendaItem[] = [
  { id: 'a1', time: '09:30', duration: '30m', title: 'Aurora standup', with: ['Maya', 'Diego', 'Priya'], status: 'recorded' },
  { id: 'a2', time: '11:00', duration: '45m', title: 'Billing migration sync', with: ['Diego', 'Tom'], status: 'upcoming' },
  { id: 'a3', time: '15:00', duration: '1h', title: 'Launch readiness review', with: ['Maya', 'Priya', 'SRE on-call'], status: 'upcoming' },
  { id: 'a4', time: '16:30', duration: '30m', title: '1:1 with Maya', with: ['Maya'], status: 'upcoming' },
];

const ACTIVITY: ActivityRow[] = [
  { id: 'e1', source: 'slack', verb: 'caught', subject: '#aurora-launch — rollout flag confirmed', atRelative: '2m ago', at: minsAgo(2), path: 'sources/slack/aurora-flag.md' },
  { id: 'e2', source: 'gmail', verb: 'filed', subject: 'Aurora launch — moving the date up', atRelative: '12m ago', at: minsAgo(12), path: 'sources/gmail/aurora-launch-date.md' },
  { id: 'e3', source: 'jira', verb: 'tracked', subject: 'AUR-142 moved to In Review', atRelative: '58m ago', at: minsAgo(58), path: 'sources/jira/AUR-142.md' },
  { id: 'e4', source: 'github', verb: 'caught', subject: 'PR #2208 — CI passed', atRelative: '1h ago', at: minsAgo(96), path: 'sources/github/pr-2208.md' },
  { id: 'e5', source: 'calendar', verb: 'noticed', subject: 'Readiness review moved to 15:00', atRelative: '3h ago', at: minsAgo(180), path: 'sources/calendar/readiness-review.md' },
  { id: 'e6', source: 'confluence', verb: 'filed', subject: 'Aurora launch plan — v4', atRelative: '4h ago', at: minsAgo(240), path: null },
];

const SUGGESTIONS: Suggestion[] = [
  { id: 's1', icon: 'calendar-clock', title: 'Prep for the 15:00 readiness review', body: 'I pulled the launch plan, the billing dry-run, and the 3 open risks into one brief.', accent: true },
  { id: 's2', icon: 'link', title: 'AUR-142 looks related to PR #2208', body: 'The billing migration and the flag cutover reference the same launch — want them linked?', accent: false },
];

const VAULT_STATS: VaultStats = {
  totalNotes: 3127,
  queuePending: 4,
  vaultSizeBytes: 268_435_456,
  lastSyncAt: minsAgo(1),
  indexedCount: 1284,
};

// 12 weeks of activity for the heatmap, weighted toward weekdays.
function heatmap(days: number): HeatmapResponse {
  const out: HeatmapResponse['days'] = [];
  let total = 0;
  let max = 0;
  for (let i = days - 1; i >= 0; i--) {
    const date = isoDay(i);
    const dow = new Date(now() - i * 86_400_000).getDay();
    const weekend = dow === 0 || dow === 6;
    // Deterministic-ish pseudo pattern from the day index (no RNG).
    const base = weekend ? (i % 5 === 0 ? 3 : 0) : 4 + ((i * 7) % 14);
    const count = base;
    if (count > 0) {
      const gmail = Math.round(count * 0.4);
      const slack = Math.round(count * 0.35);
      const rest = count - gmail - slack;
      out.push({ date, count, bySource: { gmail, slack, jira: Math.max(0, rest) } });
    } else {
      out.push({ date, count: 0, bySource: {} });
    }
    total += count;
    if (count > max) max = count;
  }
  return { days: out, total, maxCount: max };
}

// ── Jots (quick capture, fictional contexts only) ────────────────────────────

const JOT_BODIES: Record<string, string> = {
  j1: `# Aurora launch — open questions\n\n- [ ] Final go/no-go owner? (Maya?)\n- [ ] Rollback plan if billing reconcile fails\n- [x] Flag defaults off in prod — confirmed\n\nDecision: ship behind \`aurora_v2\`, flip for 10% first.`,
  j2: `Idea: a "time to first capture" onboarding metric. If a new user connects a source and sees something caught within 60s, activation jumps. Worth an experiment.`,
  j3: `Reading: *Thinking in Systems* — the bit about stock-and-flow maps to how the vault accumulates. Re-read chapter 3 before the architecture review.`,
  j4: `Groceries + weekend: book the campsite, order the tent poles, call dad Sunday.`,
};

const JOTS: JotListItem[] = [
  { id: 'j1', path: 'jots/aurora-open-questions.md', title: 'Aurora launch — open questions', excerpt: 'Final go/no-go owner? Rollback plan if billing reconcile fails…', context: 'aurora', routingStatus: 'routed', tags: ['aurora', 'launch'], created: minsAgo(90), updated: minsAgo(20) },
  { id: 'j2', path: 'jots/activation-metric-idea.md', title: 'Time-to-first-capture metric', excerpt: 'Idea: a "time to first capture" onboarding metric…', context: 'product', routingStatus: 'routed', tags: ['idea', 'metrics'], created: minsAgo(200), updated: minsAgo(120) },
  { id: 'j3', path: 'jots/thinking-in-systems.md', title: 'Reading — Thinking in Systems', excerpt: 'The bit about stock-and-flow maps to how the vault accumulates…', context: 'reading', routingStatus: 'routed', tags: ['reading'], created: minsAgo(1500), updated: minsAgo(1500) },
  { id: 'j4', path: 'jots/weekend.md', title: 'Weekend', excerpt: 'Book the campsite, order the tent poles, call dad Sunday.', context: 'personal', routingStatus: 'routed', tags: [], created: minsAgo(3000), updated: minsAgo(3000) },
];

const DAILY: DailyPage = {
  total: 18,
  items: [
    { id: 'd1', date: isoDay(0), title: 'Today', snippet: 'Aurora date moved up · billing dry-run clean · readiness review at 15:00.', noteCount: 6 },
    { id: 'd2', date: isoDay(1), title: 'Yesterday', snippet: 'Flag cutover PR opened · dashboard spec v2 shared.', noteCount: 4 },
  ],
};

const MEETINGS: MeetingsPage = {
  total: 32,
  items: [
    { id: 'm1', title: 'Aurora standup', date: isoDay(0), dur: '28m', speakers: 4, tags: ['aurora'], path: 'meetings/aurora-standup.md' },
    { id: 'm2', title: 'Architecture review — vault indexing', date: isoDay(2), dur: '52m', speakers: 5, tags: ['architecture'], path: 'meetings/arch-review.md' },
  ],
};

const SCHEDULER_STATUS = {
  enabled: true,
  running: true,
  jobs: {
    gmail: { name: 'gmail', schedule_label: 'every 5m', last_run_at: now() / 1000 - 180, last_run_ok: true, last_queued: 3, last_error: null, last_error_type: null, last_skipped_reason: null, next_run_at: now() / 1000 + 120, consecutive_failures: 0, failed_since: null, running: false },
    slack: { name: 'slack', schedule_label: 'every 2m', last_run_at: now() / 1000 - 60, last_run_ok: true, last_queued: 11, last_error: null, last_error_type: null, last_skipped_reason: null, next_run_at: now() / 1000 + 60, consecutive_failures: 0, failed_since: null, running: false },
  },
};

const SCHEDULER_DIAGNOSTICS = {
  enabled: true,
  active_launchd_plists: [],
  double_scheduling: false,
  ffmpeg_available: true,
};

const RECORDER_SETTINGS: RecorderSettings = {
  enabled: true,
  excluded_titles: [],
  manual_context: '',
};

const RECORDER_STATUS: RecorderStatus = {
  phase: 'idle',
  owner: null,
  title: null,
  startedAt: null,
  wavPath: null,
  transcriptPath: null,
  error: null,
};

// Notes opened from captures / activity / jots resolve here.
function note(path: string): Note {
  // Jot bodies first (path → jot), then capture bodies, else a generic note.
  const jot = JOTS.find((j) => j.path === path);
  if (jot) {
    return { path, title: jot.title, body: JOT_BODIES[jot.id] ?? jot.excerpt, frontmatter: { context: jot.context, tags: jot.tags } };
  }
  const cap = CAPTURES.find((c) => c.path === path);
  if (cap) {
    return { path, title: cap.title, body: CAPTURE_BODIES[cap.id] ?? cap.snippet, frontmatter: { source: cap.source, from: cap.from } };
  }
  return { path, title: path.split('/').pop() ?? 'note', body: '_(demo note)_', frontmatter: {} };
}

// ── Router ───────────────────────────────────────────────────────────────────

const ok = <T>(data: T): ApiResult<T> => ({ ok: true, data });

/** Route a demo API request. Unknown paths return an empty-but-valid shape so
 *  the UI never shows an error panel during a recording. */
export function handleDemoApi(method: string, path: string, body?: unknown): ApiResult {
  const rawPath = path.split('?')[0] ?? path;
  const query = path.split('?')[1] ?? '';
  const params = new URLSearchParams(query);
  const seg = rawPath.replace(/^\/v1\//, '').split('/');
  const s1 = seg[1] ?? '';

  // Notes endpoint is overloaded: ?path= → single note; ?source=manual → jots.
  if (rawPath === '/v1/notes') {
    if (method === 'GET' && params.get('path')) return ok(note(params.get('path')!));
    if (method === 'GET') {
      const jots: JotsPage = { items: JOTS, total: JOTS.length };
      return ok(jots);
    }
  }

  switch (`${method} /v1/${seg[0]}`) {
    case 'GET /v1/vault':
      return ok(VAULT_STATS);
    case 'GET /v1/connectors':
      if (seg.length === 1) return ok(CONNECTORS);
      return ok(connectorDetail(s1) ?? connectorDetail('gmail')!);
    case 'POST /v1/connectors': {
      // sync-all → map; <id>/sync → single result
      if (s1 === 'sync-all') {
        const out: Record<string, unknown> = {};
        for (const c of CONNECTORS.filter((c) => c.state === 'on')) {
          out[c.id] = { connector: c.id, ok: true, queued: (c.id.length % 4) + 1, error: null, skipped_reason: null };
        }
        return ok(out);
      }
      return ok({ connector: s1, ok: true, queued: 2, error: null, skipped_reason: null });
    }
    case 'GET /v1/captures':
      if (seg.length > 1) return ok(captureDetail(decodeURIComponent(s1)) ?? captureDetail('c1')!);
      {
        const source = params.get('source');
        const items = source ? CAPTURES.filter((c) => c.source === source) : CAPTURES;
        const page: CapturesPage = { total: items.length, items };
        return ok(page);
      }
    case 'GET /v1/agenda':
      return ok(AGENDA);
    case 'GET /v1/activity':
      if (s1 === 'heatmap') return ok(heatmap(Number(params.get('days')) || 365));
      return ok(ACTIVITY);
    case 'GET /v1/suggestions':
      return ok(SUGGESTIONS);
    case 'GET /v1/daily':
      return ok(DAILY);
    case 'GET /v1/meetings':
      return ok(MEETINGS);
    case 'GET /v1/scheduler':
      if (s1 === 'diagnostics') return ok(SCHEDULER_DIAGNOSTICS);
      return ok(SCHEDULER_STATUS);
    case 'GET /v1/settings':
      return ok(RECORDER_SETTINGS);
    case 'POST /v1/settings':
      return ok({ ...RECORDER_SETTINGS, ...(body as object) });
    case 'GET /v1/recorder':
      return ok(RECORDER_STATUS);
    case 'GET /v1/chat':
      if (seg.length === 1) return ok(listConversations());
      return ok(getConversation(decodeURIComponent(s1)));
    case 'POST /v1/chat':
      // "new chat" — hand back the single demo conversation.
      return ok(getConversation(DEMO_CONVERSATION_ID));
    case 'PATCH /v1/chat':
      return ok(getConversation(decodeURIComponent(s1 || DEMO_CONVERSATION_ID)));
    case 'DELETE /v1/chat':
      return ok({ ok: true });
    default:
      break;
  }

  // Jot mutations / note updates — acknowledge so the UI stays happy.
  if (rawPath.startsWith('/v1/notes/')) {
    return ok({ id: seg[2] ?? 'demo', path: 'jots/demo.md', routingStatus: 'routed', context: 'product', updated: minsAgo(0) });
  }

  // Default: empty list / null so React Query resolves without an error panel.
  return ok([]);
}

// Re-export chat state hooks for the chat module + index.ts.
export { CAPTURES, CONNECTORS, JOTS };

// ── Demo settings (clean, deterministic — never the user's real config) ──────

export const DEMO_SETTINGS = {
  theme: 'dark' as const,
  density: 'comfortable' as const,
  vaultPath: '/Users/you/vault',
  dailyNoteEnabled: true,
  markdownFrontmatter: true,
  autoLinkMentions: true,
  cloudSync: false,
  e2eEncryption: true,
  telemetry: false,
  llmProvider: 'local' as const,
  autoRecordFromCalendar: true,
  diarizeSpeakers: true,
  extractActionItems: true,
  audioRetention: '30d' as const,
  transcriptModel: 'whisper-large-v3' as const,
  folderStructure: 'by-source' as const,
  schedulerEnabled: true,
  hotkeys: { jotOverlay: 'Alt+J' },
};

// ── Conversations (chat) — stateful so a live turn appends correctly ─────────

const CONV_ID = 'demo-aurora';

const conversation: Conversation = {
  id: CONV_ID,
  title: 'Aurora launch — what did we decide?',
  created_at: now() / 1000 - 3600,
  updated_at: now() / 1000 - 1800,
  claude_session_id: 'demo-session',
  messages: [
    {
      role: 'user',
      text: 'Catch me up on the Aurora launch — where did we land on the date and what is still open?',
    },
    {
      role: 'assistant',
      tools: [{ name: 'search_vault', summary: 'searched vault · 9 hits' }],
      text: `Here's where Aurora stands, pulled from the last few days:\n\n- **Date:** moved up to **Thursday next week** — Maya asked to lock it in standup.\n- **Rollout:** behind the \`aurora_v2\` flag, default off in prod, 10% first.\n- **Billing (AUR-142):** dry-run clean (0/41k failed). One follow-up: reconcile 3 legacy currency codes.\n\n**Still open:** who owns the final go/no-go, and the rollback plan if reconcile fails.`,
    },
  ],
};

export function listConversations(): ConversationSummary[] {
  return [
    {
      id: conversation.id,
      title: conversation.title,
      created_at: conversation.created_at,
      updated_at: conversation.updated_at,
      message_count: conversation.messages.length,
    },
  ];
}

export function getConversation(id: string): Conversation {
  // Single demo conversation; ignore id mismatches gracefully.
  return id === conversation.id ? conversation : conversation;
}

/** Append a completed turn so the post-stream refetch shows it in the thread. */
export function appendTurn(userText: string, assistantText: string, toolSummary: string): void {
  conversation.messages.push({ role: 'user', text: userText });
  conversation.messages.push({
    role: 'assistant',
    text: assistantText,
    tools: [{ name: 'search_vault', summary: toolSummary }],
  });
  conversation.updated_at = now() / 1000;
}

export const DEMO_CONVERSATION_ID = CONV_ID;
