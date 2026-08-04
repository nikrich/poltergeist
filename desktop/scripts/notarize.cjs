// afterSign hook for electron-builder. Runs `xcrun notarytool` against the
// freshly-signed .app, then staples the notarization ticket.
//
// Skipped when:
//   - Not building on macOS
//   - SKIP_NOTARIZE=1 is set (used for unsigned dev builds)
//   - APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID are missing
//
// We shell out to notarytool directly (instead of using @electron/notarize)
// so we can:
//   - Print Apple's per-submission history at start.
//   - Capture the submission ID immediately on submit, not after wait returns.
//   - Poll status with periodic logs so a stuck run shows progress.
//   - Always dump the notary log on any non-Accepted result.

const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const NOTARY_MAX_WAIT_MS = 90 * 60 * 1000; // 90 min — workflow caps at 120
const POLL_INTERVAL_MS = 30 * 1000;
const HISTORY_LIMIT = 10;

function run(cmd, args, opts = {}) {
  // spawnSync (not execSync) — args is an array so no shell interpolation.
  const result = spawnSync(cmd, args, { encoding: 'utf-8', ...opts });
  if (result.error) throw result.error;
  return result;
}

function withCreds(args, creds) {
  return [
    ...args,
    '--apple-id', creds.appleId,
    '--password', creds.password,
    '--team-id', creds.teamId,
  ];
}

function printHistory(creds) {
  console.log('[notarize] recent submission history for this team:');
  const result = run('xcrun', withCreds(
    ['notarytool', 'history', '--output-format', 'plain'],
    creds,
  ));
  if (result.status !== 0) {
    console.warn('[notarize] history call failed:', result.stderr || result.stdout);
    return;
  }
  const lines = result.stdout.split('\n').slice(0, HISTORY_LIMIT + 2);
  for (const line of lines) console.log(`[notarize] | ${line}`);
}

function submitForId(zipPath, creds) {
  console.log('[notarize] submitting to Apple notary (no-wait, capture ID)...');
  const result = run('xcrun', withCreds(
    ['notarytool', 'submit', zipPath, '--output-format', 'json'],
    creds,
  ));
  if (result.status !== 0) {
    throw new Error(`notarytool submit failed: ${result.stderr || result.stdout}`);
  }
  let parsed;
  try {
    parsed = JSON.parse(result.stdout);
  } catch (e) {
    throw new Error(`could not parse notarytool submit output: ${result.stdout}`);
  }
  console.log('[notarize] submitted →', parsed);
  if (!parsed.id) {
    throw new Error('notarytool submit returned no id');
  }
  return parsed.id;
}

function fetchStatus(id, creds) {
  const result = run('xcrun', withCreds(
    ['notarytool', 'info', id, '--output-format', 'json'],
    creds,
  ));
  if (result.status !== 0) {
    return { status: 'Error', stderr: result.stderr || result.stdout };
  }
  try {
    return JSON.parse(result.stdout);
  } catch {
    return { status: 'Error', raw: result.stdout };
  }
}

function fetchLog(id, creds) {
  const result = run('xcrun', withCreds(['notarytool', 'log', id], creds));
  return result.stdout || result.stderr || '(empty log)';
}

async function pollUntilDone(id, creds) {
  const start = Date.now();
  let lastStatus = null;
  while (Date.now() - start < NOTARY_MAX_WAIT_MS) {
    const info = fetchStatus(id, creds);
    const status = info.status || '(unknown)';
    const elapsed = Math.round((Date.now() - start) / 1000);
    if (status !== lastStatus) {
      console.log(`[notarize] t+${elapsed}s status=${status}`);
      lastStatus = status;
    } else {
      console.log(`[notarize] t+${elapsed}s status=${status} (unchanged)`);
    }
    if (status === 'Accepted' || status === 'Invalid' || status === 'Rejected') {
      return info;
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  return { status: 'Timeout', elapsedMs: Date.now() - start };
}

function zipApp(appPath) {
  // ditto produces a .zip in the canonical macOS layout that notarytool
  // accepts. The .app on disk is what we ship; the .zip is just transport.
  const zipPath = `${appPath}.notarize.zip`;
  if (fs.existsSync(zipPath)) fs.unlinkSync(zipPath);
  console.log('[notarize] packing →', zipPath);
  const result = run('/usr/bin/ditto', ['-c', '-k', '--keepParent', appPath, zipPath]);
  if (result.status !== 0) {
    throw new Error(`ditto pack failed: ${result.stderr || result.stdout}`);
  }
  return zipPath;
}

function staple(appPath) {
  console.log('[notarize] stapling ticket to', appPath);
  const result = run('xcrun', ['stapler', 'staple', appPath], { stdio: 'inherit' });
  if (result.status !== 0) {
    throw new Error(`stapler failed (exit ${result.status})`);
  }
}

exports.default = async function notarizing(context) {
  const { electronPlatformName, appOutDir, packager } = context;
  if (electronPlatformName !== 'darwin') return;
  if (process.env.SKIP_NOTARIZE === '1') {
    console.log('[notarize] SKIP_NOTARIZE=1 — skipping');
    return;
  }
  const { APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID } = process.env;
  if (!APPLE_ID || !APPLE_APP_SPECIFIC_PASSWORD || !APPLE_TEAM_ID) {
    console.warn(
      '[notarize] APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID not set — skipping.',
    );
    return;
  }
  const creds = {
    appleId: APPLE_ID,
    password: APPLE_APP_SPECIFIC_PASSWORD,
    teamId: APPLE_TEAM_ID,
  };

  const appName = packager.appInfo.productFilename;
  const appPath = path.join(appOutDir, `${appName}.app`);
  console.log('[notarize] app path:', appPath);

  // Step 1: history snapshot — if this team has many In Progress entries
  // older than today, Apple is sitting on them, not failing them.
  printHistory(creds);

  // Step 2: zip and submit. We don't use --wait so we get the ID up front.
  const zipPath = zipApp(appPath);
  const submissionId = submitForId(zipPath, creds);

  // Step 3: poll explicitly so log lines show progress every 30s.
  const result = await pollUntilDone(submissionId, creds);
  console.log('[notarize] final result:', JSON.stringify(result, null, 2));

  // Step 4: always fetch the log. Even on Accepted it has useful diagnostics.
  try {
    const log = fetchLog(submissionId, creds);
    console.log('[notarize] ── full notary log ──');
    console.log(log);
    console.log('[notarize] ── end log ──');
  } catch (e) {
    console.warn('[notarize] could not fetch log:', e.message || e);
  }

  if (result.status !== 'Accepted') {
    throw new Error(
      `notarization did not succeed: status=${result.status} id=${submissionId}`,
    );
  }

  staple(appPath);
  console.log('[notarize] done');
};
