/** Setup recipes for each connector, surfaced in the Setup screen.
 *
 * Sources every step from the project README so this stays a single
 * source of truth at install time — drift between README and the in-app
 * guide is caught by reviewing this file when the README changes.
 */

export interface SetupStep {
  /** Plain-text instruction, no markdown. */
  text: string;
  /** Optional shell command to copy. */
  command?: string;
  /** Optional follow-up note shown beneath the command. */
  note?: string;
}

export interface ConnectorRecipe {
  id: string;
  displayName: string;
  blurb: string;          // 1-2 sentence summary of what this connector pulls
  prereqs: string[];
  steps: SetupStep[];
  manualCommand?: string; // command users can run to do a manual fetch
}

export const RECIPES: ConnectorRecipe[] = [
  {
    id: 'claude_code',
    displayName: 'Claude Code',
    blurb:
      'Captures finished Claude Code sessions via the SessionEnd hook. Routes the digest to a context based on the project path.',
    prereqs: [
      'Claude Code CLI installed (claude --version works).',
      'A SessionEnd entry in ~/.claude/settings.json pointing at the hook script.',
    ],
    steps: [
      {
        text: 'Add this entry to ~/.claude/settings.json under "hooks":',
        command:
          '"SessionEnd": [{ "matcher": "*", "hooks": [{ "type": "command", "command": "/Users/jannik/development/nikrich/ghost-brain/orchestration/hooks/session-end.sh", "shell": "bash", "async": true }] }]',
      },
      {
        text:
          'Map your project paths to a context in <vault>/90-meta/routing.yaml under claude_code.project_paths. Longest-prefix match wins.',
      },
      {
        text:
          'End a Claude Code session in any mapped project. A capture should land under 00-inbox/raw/claude-code/ within 5 seconds.',
      },
    ],
  },
  {
    id: 'github',
    displayName: 'GitHub',
    blurb:
      'Polls every 2 hours for PRs you authored, PRs requesting your review, and issues assigned to you — filtered to orgs in routing.yaml.',
    prereqs: ['gh CLI installed and logged in (gh auth status succeeds).'],
    steps: [
      {
        text: 'Log into GitHub via gh:',
        command: 'gh auth login',
      },
      {
        text: 'Map your orgs to contexts in <vault>/90-meta/routing.yaml:',
        command:
          'github:\n  orgs:\n    YourOrg: codeship\n    YourEmployer: work',
      },
      {
        text: 'Schedule the launchd plist (already templated for your machine):',
        command:
          'launchctl load ~/Library/LaunchAgents/com.ghostbrain.github.plist',
      },
    ],
    manualCommand: 'ghostbrain-github-fetch --dry-run',
  },
  {
    id: 'jira',
    displayName: 'Jira',
    blurb:
      'Every 4h, fetches tickets where you are assignee, reporter, or watcher and have been updated within the lookback window.',
    prereqs: [
      'Atlassian API token from https://id.atlassian.com/manage-profile/security/api-tokens.',
      'ATLASSIAN_EMAIL and ATLASSIAN_TOKEN_<SITE> set in your shell .env.',
    ],
    steps: [
      {
        text:
          'Generate an API token at id.atlassian.com/manage-profile/security/api-tokens.',
      },
      {
        text:
          'Add to ~/.ghostbrain/.env (or your shell env). <SITE> is the site slug uppercased — e.g. sft.atlassian.net → SFT.',
        command:
          'ATLASSIAN_EMAIL=your.email@example.com\nATLASSIAN_TOKEN_SFT=<api token>',
      },
      {
        text: 'Map your Jira site(s) to contexts in routing.yaml:',
        command: 'jira:\n  sites:\n    sft.atlassian.net: sanlam',
      },
      {
        text: 'Load the launchd schedule:',
        command:
          'launchctl load ~/Library/LaunchAgents/com.ghostbrain.jira.plist',
      },
    ],
    manualCommand: 'ghostbrain-jira-fetch --dry-run',
  },
  {
    id: 'confluence',
    displayName: 'Confluence',
    blurb:
      'Daily at 06:00, pulls pages updated in monitored spaces. Reuses the same Atlassian token as Jira.',
    prereqs: [
      'Same Atlassian token as Jira (set ATLASSIAN_EMAIL + ATLASSIAN_TOKEN_<SITE>).',
    ],
    steps: [
      {
        text:
          'Find the space keys you want to monitor (visible in any Confluence page URL: .../wiki/spaces/<KEY>/...).',
      },
      {
        text: 'Map them to contexts in routing.yaml:',
        command:
          'confluence:\n  sites:\n    sft.atlassian.net: sanlam\n  spaces:\n    DIG: sanlam\n    ASCP: sanlam',
      },
      {
        text: 'Load the launchd schedule:',
        command:
          'launchctl load ~/Library/LaunchAgents/com.ghostbrain.confluence.plist',
      },
    ],
    manualCommand: 'ghostbrain-confluence-fetch --dry-run',
  },
  {
    id: 'calendar',
    displayName: 'Calendar',
    blurb:
      'macOS Calendar app + optional Google calendars, polled hourly. Today\'s events feed the morning digest and prime the recorder.',
    prereqs: [
      'For macOS: just grant Calendar permission the first time it runs.',
      'For Google: a Google Cloud project with the Calendar API enabled + Desktop OAuth client at ~/.ghostbrain/state/google_oauth_client.json.',
    ],
    steps: [
      {
        text:
          'Configure macOS calendar accounts in routing.yaml (calendar_name → context):',
        command:
          'calendar:\n  macos:\n    accounts:\n      Calendar: personal\n      Work: work',
      },
      {
        text: 'For Google: run consent once per account:',
        command: 'ghostbrain-calendar-auth google you@gmail.com',
        note:
          'Refresh tokens expire after ~7 days while the OAuth screen is in Test mode — publish the consent screen or re-auth weekly.',
      },
      {
        text: 'Load the launchd schedule:',
        command:
          'launchctl load ~/Library/LaunchAgents/com.ghostbrain.calendar.plist',
      },
    ],
    manualCommand: 'ghostbrain-calendar-fetch --dry-run',
  },
  {
    id: 'gmail',
    displayName: 'Gmail',
    blurb:
      'Routes threads that are either unread within 24h or carry a monitored label. Filters by sender domain or label prefix.',
    prereqs: [
      'Google OAuth client from the same Google Cloud project as Calendar (Gmail API enabled).',
    ],
    steps: [
      {
        text:
          'Enable the Gmail API in your Google Cloud project (reuse the calendar OAuth client).',
      },
      {
        text: 'Configure accounts + routing in routing.yaml:',
        command:
          'gmail:\n  accounts:\n    you@gmail.com:\n      monitored_labels: ["sanlam/policies"]\n      unread_lookback_hours: 24\n  sender_domains:\n    sanlam.co.za: sanlam\n  label_prefixes:\n    "sanlam/": sanlam',
      },
      {
        text: 'Run consent once per account:',
        command: 'ghostbrain-gmail-auth you@gmail.com',
      },
    ],
    manualCommand: 'ghostbrain-gmail-fetch --dry-run',
  },
  {
    id: 'slack',
    displayName: 'Slack',
    blurb:
      'Pulls @-mentions across configured workspaces from the last 24h. Mentions only — no raw channel volume.',
    prereqs: [
      'A Slack app per workspace at api.slack.com/apps.',
      'User OAuth Token (xoxp-...) with scopes: search:read, users:read, team:read, channels/groups/im/mpim:history.',
    ],
    steps: [
      {
        text:
          'Create a Slack app from scratch at api.slack.com/apps → name "poltergeist" → pick the workspace.',
      },
      {
        text:
          'Add User Token Scopes: search:read, users:read, team:read, channels:history, groups:history, im:history, mpim:history. Install to Workspace → copy the User OAuth Token.',
      },
      {
        text:
          'Save the token (slug is whatever you want to use in routing.yaml):',
        command: 'ghostbrain-slack-token-add <slug> xoxp-...your-token...',
      },
      {
        text: 'Configure the workspace in routing.yaml:',
        command:
          'slack:\n  workspaces:\n    sft:\n      context: sanlam\n      lookback_hours: 24\n      mentions_only: true',
      },
    ],
    manualCommand: 'ghostbrain-slack-fetch --dry-run',
  },
];

export function recipeForId(id: string): ConnectorRecipe | undefined {
  return RECIPES.find((r) => r.id === id);
}
