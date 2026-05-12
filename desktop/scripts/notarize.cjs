// afterSign hook for electron-builder. Runs `notarytool submit ... --wait`
// against the freshly-signed .app, then staples the notarization ticket.
//
// Skipped when:
//   - Not building on macOS
//   - SKIP_NOTARIZE=1 is set (used for unsigned dev builds)
//   - APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID are missing
//     (we warn rather than fail so contributors without Apple credentials can
//     still produce a local build for sanity-checking the bundle layout)

const path = require('node:path');
const { notarize } = require('@electron/notarize');

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
      '[notarize] APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID not set — skipping. ' +
        'The produced .app will not pass Gatekeeper on other machines.',
    );
    return;
  }
  const appName = packager.appInfo.productFilename;
  const appPath = path.join(appOutDir, `${appName}.app`);
  console.log(`[notarize] submitting ${appPath} to Apple...`);
  await notarize({
    tool: 'notarytool',
    appPath,
    appleId: APPLE_ID,
    appleIdPassword: APPLE_APP_SPECIFIC_PASSWORD,
    teamId: APPLE_TEAM_ID,
  });
  console.log('[notarize] done');
};
