export interface AgendaItem {
  time: string;
  dur: string;
  title: string;
  with: string[];
  status: 'upcoming' | 'recorded';
}
export interface ActivityRow {
  source: string;
  verb: string;
  subject: string;
  time: string;
}
export interface ConnectorPulse {
  name: string;
  state: 'on' | 'off' | 'err';
  count: string;
}
export interface CaptureLatelyItem {
  source: string;
  title: string;
  snippet: string;
  from: string;
}
export interface Suggestion {
  icon: string;
  title: string;
  body: string;
  accent?: boolean;
}

export const AGENDA: AgendaItem[] = [
  {
    time: '11:00',
    dur: '30m',
    title: 'Design crit · onboarding v3',
    with: ['mira', 'jules', 'sam'],
    status: 'upcoming',
  },
  { time: '14:30', dur: '60m', title: 'Weekly with Theo', with: ['theo'], status: 'upcoming' },
  { time: '09:00', dur: '20m', title: 'standup', with: ['team'], status: 'recorded' },
];

export const ACTIVITY: ActivityRow[] = [
  { source: 'gmail', verb: 'archived', subject: '3 newsletters', time: '2m' },
  { source: 'slack', verb: 'captured', subject: '#design-crit thread', time: '5m' },
  { source: 'linear', verb: 'linked', subject: 'GHO-241 → meeting notes', time: '14m' },
  { source: 'notion', verb: 'watching', subject: 'Q2 roadmap', time: '22m' },
  { source: 'calendar', verb: 'indexed', subject: '3 events', time: '38m' },
  { source: 'gmail', verb: 'extracted', subject: 'action item from theo', time: '1h' },
];

export const CONNECTOR_PULSES: ConnectorPulse[] = [
  { name: 'gmail', state: 'on', count: '14.8k' },
  { name: 'slack', state: 'on', count: '9.4k' },
  { name: 'notion', state: 'on', count: '1.1k' },
  { name: 'linear', state: 'on', count: '824' },
  { name: 'calendar', state: 'on', count: '412' },
  { name: 'github', state: 'err', count: '—' },
  { name: 'drive', state: 'off', count: '—' },
];

export const CAUGHT_LATELY: CaptureLatelyItem[] = [
  {
    source: 'gmail',
    title: 're: design crit moved',
    snippet: 'works for me — moving the 11am to thursday next week.',
    from: 'theo · 8:14am',
  },
  {
    source: 'slack',
    title: '#product-feedback',
    snippet: 'users keep asking for keyboard shortcuts on the meetings view. ranked it as p1.',
    from: 'mira · 8:01am',
  },
  {
    source: 'linear',
    title: 'GHO-241 closed',
    snippet: 'recording auto-pause when system sleeps. shipped in 1.4.2.',
    from: 'jules · 7:48am',
  },
];

export const SUGGESTIONS: Suggestion[] = [
  {
    icon: 'link',
    title: 'connect drive',
    body: '3 mentions of shared docs in slack this week — none are indexed.',
  },
  {
    icon: 'user-plus',
    title: 'follow up with @sam',
    body: 'last reply from sam was 9 days ago. on a thread you starred.',
  },
  {
    icon: 'sparkles',
    title: 'weekly digest is ready',
    body: 'summary of 24 captured threads, ready to drop into your daily note.',
    accent: true,
  },
];

export const STATS = {
  captured: { label: 'captured', value: '241', delta: '+38 vs yest' },
  meetings: { label: 'meetings', value: '2', delta: 'next in 23m' },
  followups: { label: 'followups', value: '8', delta: '3 overdue' },
  vaultSize: { label: 'vault size', value: '2,489', delta: 'notes' },
};
