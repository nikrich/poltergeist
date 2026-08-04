// Recording UI stub data. The history portion of the meetings screen
// reads real data from the sidecar (via useMeetings), but the
// pre/recording/post state machine is UI-only in Phase 1 — Slice 4 will
// wire it to the real poltergeist.recorder. Until then, these constants
// drive the static portions of that UI (participant list, sample
// transcript lines, fake speaker airtime percentages).

export interface Participant {
  name: string;
  role: string;
  color: string;
}

export interface TranscriptLine {
  who: string;
  color: string;
  t: string;
  text: string;
  live: boolean;
}

// Per-participant avatar colors. These are mock data — in real usage they come
// from the user record. Hex values intentionally mirror the theme accents
// (neon, oxblood, pill-water-fg, pill-moss-fg) so the demo looks on-brand.
export const PARTICIPANTS: Participant[] = [
  { name: 'mira', role: 'design lead', color: '#C5FF3D' },
  { name: 'jules', role: 'eng', color: '#FF6B5A' },
  { name: 'sam', role: 'pm', color: '#7FB3D5' },
  { name: 'you', role: 'host', color: '#A2C795' },
];

// Per-line speaker color, kept in sync with PARTICIPANTS above (mock data).
export const TRANSCRIPT: TranscriptLine[] = [
  {
    who: 'mira',
    color: '#C5FF3D',
    t: '00:12',
    text: 'okay so the onboarding flow — i think the third screen is doing too much.',
    live: false,
  },
  {
    who: 'jules',
    color: '#FF6B5A',
    t: '00:24',
    text: 'agreed. we should split the connector picker out from the vault setup.',
    live: false,
  },
  {
    who: 'sam',
    color: '#7FB3D5',
    t: '00:38',
    text: 'what if connectors are deferred entirely? you can install poltergeist and do it later.',
    live: false,
  },
  {
    who: 'you',
    color: '#A2C795',
    t: '00:54',
    text: "i'd want at least one connected before the welcome state — otherwise the dashboard is empty.",
    live: false,
  },
  {
    who: 'mira',
    color: '#C5FF3D',
    t: '01:08',
    text: "right. minimum one. let's call that out as a soft requirement.",
    live: true,
  },
];

export const SPEAKER_AIRTIME = [34, 28, 22, 16];
