export interface CaptureRecord {
  id: number;
  source: string;
  title: string;
  snippet: string;
  from: string;
  tags: string[];
  unread?: boolean;
}

export const CAPTURE_ITEMS: CaptureRecord[] = [
  {
    id: 1,
    source: 'gmail',
    title: 're: design crit moved',
    snippet: "works for me — moving the 11am to thursday next week. can you ping mira if she's in?",
    from: 'theo · 8:14am',
    tags: ['followup'],
    unread: true,
  },
  {
    id: 2,
    source: 'slack',
    title: '#product-feedback',
    snippet: 'users keep asking for keyboard shortcuts on the meetings view. ranked it as p1.',
    from: 'mira · 8:01am',
    tags: ['feedback', 'p1'],
    unread: true,
  },
  {
    id: 3,
    source: 'linear',
    title: 'GHO-241 closed',
    snippet: 'recording auto-pause when system sleeps. shipped in 1.4.2. nice work everyone.',
    from: 'jules · 7:48am',
    tags: ['shipped'],
  },
  {
    id: 4,
    source: 'notion',
    title: 'Q2 roadmap · edited',
    snippet: 'theo updated the connector roadmap. drive moved up, hubspot moved down.',
    from: 'theo · 7:32am',
    tags: ['roadmap'],
  },
  {
    id: 5,
    source: 'calendar',
    title: 'design crit moved',
    snippet: 'time changed: thursday 11:00 → 11:30. 30 min. attendees notified.',
    from: 'cal · 7:15am',
    tags: [],
  },
  {
    id: 6,
    source: 'gmail',
    title: 'invoice from lattice',
    snippet: 'payment received. attached pdf. nothing for you to do.',
    from: 'billing · yesterday',
    tags: ['archived'],
  },
  {
    id: 7,
    source: 'slack',
    title: '@you in #design',
    snippet: 'sam: "love the new ghost float — felt like a real ghost for half a second"',
    from: 'sam · yesterday',
    tags: ['mention'],
  },
  {
    id: 8,
    source: 'github',
    title: 'PR #482 merged',
    snippet: 'feat: live transcript diarization. +482 / -91. tests green.',
    from: 'jules · 2d',
    tags: ['shipped'],
  },
];
