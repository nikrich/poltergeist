/** Single source of truth for connector cards and their auth patterns.
 *
 * Each card describes a connector (id), its display properties, auth method,
 * and optional grouping. Used by F2 ConnectorAuthFlow, G1 connectors screen,
 * and G2 wizard to drive authentication and connector setup.
 */

export type AuthPattern = 'google_oauth' | 'ms_device_code' | 'paste_token' | 'atlassian_api' | 'cli_login' | 'local_grant';

export interface ConnectorCard {
  /** Connector id used in API paths (e.g. 'gmail'). Must match backend connector ids. */
  id: string;
  /** Display name shown in UI. */
  displayName: string;
  /** 1-2 sentence summary of what this connector pulls. */
  blurb: string;
  /** Authentication pattern used by this connector. */
  pattern: AuthPattern;
  /** Optional deep link to create credentials (e.g. Google Cloud console, api.slack.com). */
  docsUrl?: string;
  /** Optional grouping key (e.g. 'google', 'atlassian') to co-present related cards. */
  group?: string;
  /** Optional sub-connectors enabled by this card (e.g. microsoft card enables outlook_mail, teams_chat, teams_meetings). */
  subConnectors?: string[];
}

export const CONNECTOR_CARDS: ConnectorCard[] = [
  {
    id: 'gmail',
    displayName: 'Gmail',
    blurb: 'Routes threads that are either unread within 24h or carry a monitored label. Filters by sender domain or label prefix.',
    pattern: 'google_oauth',
    docsUrl: 'https://console.cloud.google.com/apis/credentials',
    group: 'google',
  },
  {
    id: 'calendar',
    displayName: 'Calendar',
    blurb: 'macOS Calendar app + optional Google calendars, polled hourly. Today\'s events feed the morning digest and prime the recorder.',
    pattern: 'google_oauth',
    docsUrl: 'https://console.cloud.google.com/apis/credentials',
    group: 'google',
  },
  {
    id: 'slack',
    displayName: 'Slack',
    blurb: 'Pulls @-mentions across configured workspaces from the last 24h. Mentions only — no raw channel volume.',
    pattern: 'paste_token',
    docsUrl: 'https://api.slack.com/apps',
  },
  {
    id: 'github',
    displayName: 'GitHub',
    blurb: 'Polls every 2 hours for PRs you authored, PRs requesting your review, and issues assigned to you — filtered to orgs in routing.yaml.',
    pattern: 'cli_login',
  },
  {
    id: 'jira',
    displayName: 'Jira',
    blurb: 'Every 4h, fetches tickets where you are assignee, reporter, or watcher and have been updated within the lookback window.',
    pattern: 'atlassian_api',
    docsUrl: 'https://id.atlassian.com/manage-profile/security/api-tokens',
    group: 'atlassian',
  },
  {
    id: 'confluence',
    displayName: 'Confluence',
    blurb: 'Daily at 06:00, pulls pages updated in monitored spaces. Reuses the same Atlassian token as Jira.',
    pattern: 'atlassian_api',
    docsUrl: 'https://id.atlassian.com/manage-profile/security/api-tokens',
    group: 'atlassian',
  },
  {
    id: 'joplin',
    displayName: 'Joplin',
    blurb: 'Captures web-clipped notes from the Joplin Web Clipper browser extension. Pulls notes updated since last sync.',
    pattern: 'paste_token',
    docsUrl: 'https://joplinapp.org/help/apps/clipper/',
  },
  {
    id: 'macos_calendar',
    displayName: 'macOS Calendar',
    blurb: 'Polls the native macOS Calendar app for today\'s events. Requires Calendar app permission on first run.',
    pattern: 'local_grant',
  },
  {
    id: 'claude_code',
    displayName: 'Claude Code',
    blurb: 'Captures finished Claude Code sessions via the SessionEnd hook. Routes the digest to a context based on the project path.',
    pattern: 'local_grant',
  },
  {
    id: 'outlook_mail',
    displayName: 'Microsoft',
    blurb: 'Outlook Mail, Teams Chat, and Teams Meetings via Microsoft device code flow. Connects your Microsoft account once, enabling all three services.',
    pattern: 'ms_device_code',
    docsUrl: 'https://portal.azure.com',
    group: 'microsoft',
    subConnectors: ['outlook_mail', 'teams_chat', 'teams_meetings'],
  },
];

export function cardForId(id: string): ConnectorCard | undefined {
  return CONNECTOR_CARDS.find((c) => c.id === id);
}
