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

export interface PastMeeting {
  date: string;
  title: string;
  dur: string;
  speakers: number;
  tags: string[];
}

export const PARTICIPANTS: Participant[] = [
  { name: 'mira', role: 'design lead', color: '#C5FF3D' },
  { name: 'jules', role: 'eng', color: '#FF6B5A' },
  { name: 'sam', role: 'pm', color: '#7FB3D5' },
  { name: 'you', role: 'host', color: '#A2C795' },
];

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
    text: 'what if connectors are deferred entirely? you can install ghostbrain and do it later.',
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

export const HISTORY: PastMeeting[] = [
  {
    date: 'mon · may 5',
    title: 'weekly with theo',
    dur: '47:22',
    speakers: 2,
    tags: ['1:1', 'roadmap'],
  },
  {
    date: 'fri · may 2',
    title: 'q2 planning offsite',
    dur: '2:12:08',
    speakers: 6,
    tags: ['planning'],
  },
  {
    date: 'thu · may 1',
    title: 'design crit · onboarding v2',
    dur: '32:14',
    speakers: 4,
    tags: ['design'],
  },
  {
    date: 'tue · apr 29',
    title: 'jules <> mira pairing',
    dur: '54:01',
    speakers: 2,
    tags: ['eng'],
  },
  { date: 'mon · apr 28', title: 'all hands', dur: '1:04:33', speakers: 12, tags: ['team'] },
];

export const SPEAKER_AIRTIME = [34, 28, 22, 16];
