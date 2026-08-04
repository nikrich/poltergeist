# Releasing GhostBrain Desktop

## How it works

1. Commits to `main` use [Conventional Commits](https://www.conventionalcommits.org/). `feat:` bumps minor, `fix:` bumps patch, `feat!:` bumps major (post-1.0).
2. [release-please](https://github.com/googleapis/release-please) maintains a release PR on `main` that bumps `desktop/package.json`, updates `desktop/CHANGELOG.md`, and lists the changes drawn from those commits.
3. Merging the release PR cuts a git tag (e.g. `v0.2.0`) and creates a GitHub Release.
4. The `build-mac` job then builds the Python sidecar with PyInstaller, packages the Electron app with electron-builder, signs + notarizes, and uploads `.dmg` + `.zip` assets to that GitHub Release.

## Required GitHub Actions secrets

Set these under **Settings → Secrets and variables → Actions**:

| Secret | What it is |
| --- | --- |
| `CSC_LINK` | Base64-encoded `.p12` of the **Developer ID Application** certificate. Export from Keychain Access → right-click cert → Export → `.p12`, then `base64 -i cert.p12 \| pbcopy`. |
| `CSC_KEY_PASSWORD` | The password you set when exporting the `.p12`. |
| `APPLE_ID` | The Apple ID email for the developer account. |
| `APPLE_APP_SPECIFIC_PASSWORD` | An app-specific password generated at https://appleid.apple.com → Sign-In and Security → App-Specific Passwords. NOT your Apple ID password. |
| `APPLE_TEAM_ID` | 10-char Team ID from https://developer.apple.com/account → Membership. |

## Local builds

```sh
# Unsigned dev build — produces a .app that only opens on this machine.
cd desktop
npm run pack:unsigned

# Signed + notarized build — needs the env vars above set locally.
cd desktop
export CSC_LINK="$(base64 -i /path/to/cert.p12)"
export CSC_KEY_PASSWORD=...
export APPLE_ID=...
export APPLE_APP_SPECIFIC_PASSWORD=...
export APPLE_TEAM_ID=...
npm run pack
```

The Python sidecar must be built first; CI does this automatically, but locally:

```sh
# From repo root, with the project venv active:
pip install pyinstaller==6.11.1
pyinstaller packaging/sidecar.spec \
  --distpath desktop/resources/sidecar \
  --workpath packaging/build \
  --noconfirm
```

## Migrating from launchd to the in-app scheduler

The desktop app can run all connectors + the worker + the recorder daemon
itself when `schedulerEnabled` is on (Settings → Background → "Run scheduler
in-app"). This is off by default so existing launchd setups keep working.

**Cutover steps** (only when you're ready — both systems running at once will
double-fetch and race on `state/<connector>.last_run`):

1. Quit GhostBrain.
2. Run `scripts/disable-launchd.sh` from the repo root. It lists every
   `com.ghostbrain.*.plist` in `~/Library/LaunchAgents`, asks for
   confirmation, then unloads and removes them.
3. Start GhostBrain. Open Settings → Background and toggle "Run scheduler in-app".
   The sidecar restarts with `GHOSTBRAIN_SCHEDULER_ENABLED=1`.
4. Open the Connectors screen. Next-run timestamps should appear next to
   "last sync". If the diagnostic banner says "Double scheduling detected",
   step 2 missed something — recheck `~/Library/LaunchAgents`.

**Rolling back**: turn the toggle off, then reinstall the plists from
`orchestration/launchd/` (the templates need `__REPO_ROOT__` + `__VAULT_PATH__`
substituted before `launchctl load`).

## Tech debt

- **x64 (Intel) builds.** CI runs `macos-14` (arm64 native) and the electron-builder config only lists `arch: arm64`. To add Intel: extend `mac.target` with `arch: x64`, add an x64 matrix entry to the workflow (PyInstaller has to run on an x64 runner — `macos-13` — because cross-arch PyInstaller builds aren't reliable), and merge both runners' artifacts onto the same release.
- **Auto-update.** `publish: null` in `electron-builder.yml` disables electron-updater. To enable, switch it to `github` and add `electron-updater` to runtime deps, then call `autoUpdater.checkForUpdatesAndNotify()` after `app.whenReady()`. The `latest-mac.yml` we already upload is what the updater consumes.
- **Sidecar binary code-signing.** electron-builder signs `.app` contents recursively with the Developer ID, which covers the PyInstaller binary. But if hardened-runtime + notarization ever rejects a bundled native dep (torch's `.dylib`s are the usual culprit), add it to `mac.signIgnore` or sign it explicitly before electron-builder runs.
- **Notarization stapling for `.zip`.** `notarytool` staples the `.app`, but the `.zip` is built post-sign. Gatekeeper accepts notarized + stapled apps even when distributed via `.zip` — first launch hits the notarization service online. If you ever ship offline, switch to `.dmg`-only or staple the `.zip` separately.
