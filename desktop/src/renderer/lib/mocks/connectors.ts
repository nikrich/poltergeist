export type ConnectorState = 'on' | 'err' | 'off';

export interface Connector {
  id: string;
  name: string;
  src: string;
  state: ConnectorState;
  count: number;
  last: string;
  account: string;
  scopes: string[];
  pulls: string[];
  throughput: string;
  color: string;
}

export const CONNECTORS: Connector[] = [
  {
    id: 'gmail',
    name: 'gmail',
    src: 'assets/connectors/gmail.svg',
    state: 'on',
    count: 14820,
    last: '2m ago',
    account: 'theo@ghostbrain.app',
    scopes: ['read messages', 'read labels', 'read attachments'],
    pulls: ['threads', 'attachments', 'contacts'],
    throughput: '~340 msgs/day',
    color: '#EA4335',
  },
  {
    id: 'slack',
    name: 'slack',
    src: 'assets/connectors/slack.svg',
    state: 'on',
    count: 9412,
    last: '1m ago',
    account: 'ghostbrain-team',
    scopes: ['channels:history', 'users:read', 'files:read'],
    pulls: ['public channels', 'mentions', 'threads'],
    throughput: '~1.2k msgs/day',
    color: '#4A154B',
  },
  {
    id: 'notion',
    name: 'notion',
    src: 'assets/connectors/notion.svg',
    state: 'on',
    count: 1108,
    last: '5m ago',
    account: 'product workspace',
    scopes: ['read content'],
    pulls: ['pages', 'databases', 'comments'],
    throughput: '~24 docs/day',
    color: '#000',
  },
  {
    id: 'linear',
    name: 'linear',
    src: 'assets/connectors/linear.svg',
    state: 'on',
    count: 824,
    last: '4m ago',
    account: 'ghostbrain',
    scopes: ['read issues'],
    pulls: ['issues', 'comments', 'cycles'],
    throughput: '~18 issues/day',
    color: '#5E6AD2',
  },
  {
    id: 'calendar',
    name: 'calendar',
    src: 'assets/connectors/calendar.svg',
    state: 'on',
    count: 412,
    last: '12m ago',
    account: 'theo@ghostbrain.app',
    scopes: ['read events'],
    pulls: ['events', 'attendees', 'descriptions'],
    throughput: '~8 events/day',
    color: '#4285F4',
  },
  {
    id: 'github',
    name: 'github',
    src: 'assets/connectors/github.svg',
    state: 'err',
    count: 0,
    last: 'token expired 2d ago',
    account: 'theo-haunts',
    scopes: ['repo:read'],
    pulls: ['issues', 'PRs', 'commits'],
    throughput: 'paused',
    color: '#181717',
  },
  {
    id: 'drive',
    name: 'drive',
    src: 'assets/connectors/drive.svg',
    state: 'off',
    count: 0,
    last: 'never',
    account: '—',
    scopes: ['drive.metadata.readonly', 'drive.readonly'],
    pulls: ['docs', 'sheets', 'slides'],
    throughput: '—',
    color: '#1FA463',
  },
];
