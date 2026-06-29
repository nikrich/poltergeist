// Scene choreography for the Poltergeist showcase video.
//
// Pure data-ish: a single async function driven by helpers from record.mjs.
// Tweak timing/order here without touching the launch/record plumbing.
//
// ctx = { page, app, cursor, beat, log }
//   cursor.click(locator)   — glide the visible cursor to an element, then click
//   cursor.move(locator)    — glide to an element without clicking
//   cursor.type(text)       — type into the focused field at a human cadence
//   beat(ms)                — pause (let the viewer read / the UI settle)
//   log(msg)                — progress line

export async function runScenes(ctx) {
  const { page, cursor, beat, log } = ctx;

  // ── 1. Today — the "while you slept" dashboard ────────────────────────────
  log('scene: today');
  await page.waitForSelector('text=while you slept', { timeout: 15000 });
  await beat(2600);

  // ── 2. Chat — ask the archive, watch it answer ────────────────────────────
  log('scene: chat');
  await cursor.click(page.getByRole('button', { name: 'ask the archive' }));
  await beat(2200); // read the pre-existing conversation

  const composer = page.getByPlaceholder('message poltergeist…');
  await cursor.click(composer);
  await cursor.type('Draft the agenda for today’s launch readiness review.');
  await beat(500);
  await page.keyboard.press('Enter');

  // Wait for the streamed answer to begin, then let it finish typing out.
  await page.waitForSelector('text=draft agenda for the 15:00', { timeout: 20000 });
  await beat(4200);

  // ── 3. Capture — the inbox, filtered by source ────────────────────────────
  log('scene: capture');
  await cursor.click(nav(page, 'capture'));
  await beat(1600);
  await cursor.click(page.getByRole('button', { name: 'slack', exact: true }));
  await beat(1200);
  await cursor.click(page.getByText('confirm rollout flag'));
  await beat(2600);

  // ── 4. Connectors — live sync status + a real sync ────────────────────────
  log('scene: connectors');
  await cursor.click(nav(page, 'connectors'));
  await beat(1800);
  await cursor.click(page.getByRole('button', { name: 'sync all' }));
  await beat(2400); // toast: "Sync complete · N new events"
  await cursor.click(page.getByText('Linear', { exact: true }));
  await beat(2400); // error detail + reauthorize

  // ── 5. Jots — quick capture, auto-filed by context ────────────────────────
  log('scene: jots');
  await cursor.click(nav(page, 'jots'));
  await beat(2000); // newest jot auto-opens in the editor
  await cursor.click(page.getByRole('button', { name: 'Time-to-first-capture metric' }));
  await beat(2600);

  // ── 6. Back to Today — settle on the hero ─────────────────────────────────
  log('scene: return to today');
  await cursor.click(nav(page, 'today'));
  await beat(2800);
}

// Sidebar nav buttons live inside <nav class="gb-sidenav">. Scope there so a
// label like "today" can't collide with body text elsewhere.
function nav(page, label) {
  return page.locator('nav.gb-sidenav button', { hasText: new RegExp(`^\\s*${label}`, 'i') }).first();
}
