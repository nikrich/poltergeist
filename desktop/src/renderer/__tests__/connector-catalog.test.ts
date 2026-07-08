import { describe, it, expect } from 'vitest';
import { CONNECTOR_CARDS, cardForId } from '../lib/connector-catalog';

describe('connector catalog', () => {
  it('covers the nine connect cards', () => {
    const ids = CONNECTOR_CARDS.map((c) => c.id);
    expect(ids).toEqual(expect.arrayContaining([
      'gmail', 'calendar', 'slack', 'github', 'jira', 'confluence', 'joplin', 'macos_calendar', 'claude_code',
    ]));
  });
  it('every card has a known pattern', () => {
    const patterns = new Set(['google_oauth','ms_device_code','paste_token','atlassian_api','cli_login','local_grant']);
    for (const c of CONNECTOR_CARDS) expect(patterns.has(c.pattern)).toBe(true);
  });
  it('cardForId resolves', () => {
    expect(cardForId('slack')?.pattern).toBe('paste_token');
  });
});
