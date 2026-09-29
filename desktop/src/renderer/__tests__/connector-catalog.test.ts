import { existsSync } from 'node:fs';

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
  it('every card has an icon at assets/connectors/<id>.svg', () => {
    // The screens load `assets/connectors/${id}.svg` by connector id; a missing
    // file renders as a broken image. Vitest runs with cwd = desktop/.
    // macos_calendar has never had an icon — tracked separately; don't add to this list.
    const knownMissing = new Set(['macos_calendar']);
    const missing = CONNECTOR_CARDS.map((c) => c.id).filter(
      (id) => !knownMissing.has(id) && !existsSync(`src/renderer/public/assets/connectors/${id}.svg`),
    );
    expect(missing).toEqual([]);
  });
  it('cardForId resolves', () => {
    expect(cardForId('slack')?.pattern).toBe('paste_token');
  });
});
