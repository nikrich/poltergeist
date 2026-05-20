# Changelog

## [0.2.6](https://github.com/nikrich/poltergeist/compare/v0.2.5...v0.2.6) (2026-05-20)


### Bug Fixes

* **sidecar:** point `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` at `certifi`'s bundled `cacert.pem` at sidecar startup. The v0.2.5 fetch sentinel surfaced the actual root cause behind the long-running "Slack syncs but queues nothing" problem: `slack_sdk.auth_test` was failing with `[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate`. PyInstaller-bundled Python has no system CA store; requests/httpx-based connectors (Gmail, Confluence, Jira, GitHub) ship `certifi` internally so they were fine, but `slack_sdk` uses stdlib `urllib`, which calls `ssl.create_default_context()` and dies without `SSL_CERT_FILE`. The catch-all in `fetch()` ate the exception as a `log.warning` that Electron then dropped, so the UI just kept showing `last_run_ok=true, queued=0`. Promoting `certifi` from transitive to direct dep so the bundle can't lose `cacert.pem` to an upstream reshuffle. The fetch sentinel stays in place for this release so we can confirm in the packaged app that `auth_test` now passes.

## [0.2.5](https://github.com/nikrich/poltergeist/compare/v0.2.3...v0.2.5) (2026-05-19)


### Bug Fixes

* **answer:** per-type context cap so meeting transcripts reach the LLM uncapped. The previous flat 16 KB `PER_NOTE_CHAR_CAP` made sense for Confluence pages and Slack threads but chopped the back half off a ~40 KB workshop transcript — the LLM was reading the first 40 minutes of a 90-minute session and the user would ask about something said at minute 70 and get "the sources don't cover this". Notes under `transcripts/` now get a 48 KB budget; everything else keeps 16 KB. Worst-case 2 transcripts in the top-8 is 2×48 + 6×16 = 192 KB, inside Sonnet's 200 KB window.


### Diagnostics

* **slack:** extend the file-based sentinel into `_fetch_workspace_full`. v0.2.3 confirmed the allowlist resolves correctly in the bundled sidecar (11 channels) yet `slack_cursors.<slug>.json` is never advanced and `queued=0`, which means an exception is firing inside the full-pull path and being swallowed by the catch-all in `fetch()` as a `log.warning` that never reaches disk. This commit writes a one-line step trace (imports, `load_token`, `client_factory`, `auth_test`, `_list_channels`, channel loop, `score_messages`, `cursors.save`) plus the exception type + 8-frame traceback to `~/.ghostbrain/state/slack.<slug>.fetch_debug.log`. Removed in a later release once the failing step is identified.

## [0.2.3](https://github.com/nikrich/poltergeist/compare/v0.2.2...v0.2.3) (2026-05-18)


### Diagnostics

* **slack:** log the allowlist resolution path for each `_resolve_allowed_channels` call to `~/.ghostbrain/state/slack.<slug>.allowlist_debug.log`. v0.2.2 ships the state-file + env-var + yaml fallback chain, but the bundled sidecar keeps producing empty allowlists in production while the same code path with the same files works in dev. The sentinel writes which source resolved and the count from each, so we can see what the bundled runtime is actually doing.

## [0.2.2](https://github.com/nikrich/poltergeist/compare/v0.2.1...v0.2.2) (2026-05-18)


### Bug Fixes

* **slack:** read full-pull allowlist from a state file (`~/.ghostbrain/state/slack.<slug>.allowed_channels.json`) before falling back to env var or routing.yaml. The env-var path silently broke on the packaged sidecar — token vars from `.env` reached `os.environ`, but the allowlist var from the same `.env` didn't, with no error logged.
* **slack:** when `mode: full` is configured without an allowlist, fall back to mentions-only with a log warning instead of silently iterating every channel and exhausting Slack's Tier 3 rate limit (the old behavior reported `last_run_ok=true, queued=0` forever).

## [0.2.1](https://github.com/nikrich/poltergeist/compare/v0.2.0...v0.2.1) (2026-05-18)


### Bug Fixes

* **build:** add `com.apple.security.device.audio-input` entitlement so the recorder can actually capture the mic. Without it, hardened-runtime binaries are silently denied mic input by avfoundation — recordings came out as 13+ minute files of pure silence (-91 dB) and whisper produced empty transcripts.

## [0.2.0](https://github.com/nikrich/poltergeist/compare/v0.1.17...v0.2.0) (2026-05-18)


### Features

* **connectors:** add joplin connector ([5288037](https://github.com/nikrich/poltergeist/commit/5288037b5f31f8581c3b6973b4606c0d6802b01a))
* **slack:** allowed_channels whitelist for high-volume workspaces ([8427ccc](https://github.com/nikrich/poltergeist/commit/8427ccc3a46e662a863dbf67128cf37ed3acbd22))


### Bug Fixes

* **recorder:** unblock daemon-owned recordings — stop button + auto-finalize ([a793033](https://github.com/nikrich/poltergeist/commit/a793033))

## [0.1.8](https://github.com/nikrich/poltergeist/compare/v0.1.7...v0.1.8) (2026-05-13)


### Bug Fixes

* **desktop:** Hide "with " on agenda rows when no attendees ([a2c77dd](https://github.com/nikrich/poltergeist/commit/a2c77dd9df1d652aeb24eb771c72cce7b5dc5e63))

## [0.1.4](https://github.com/nikrich/ghost-brain/compare/v0.1.3...v0.1.4) (2026-05-13)


### Bug Fixes

* **desktop:** Make Obsidian wikilinks clickable in rendered markdown ([e199432](https://github.com/nikrich/ghost-brain/commit/e199432b06b6f8e010e94777ba8daade4699bd80))

## [0.1.1](https://github.com/nikrich/ghost-brain/compare/v0.1.0...v0.1.1) (2026-05-12)


### Features

* **api+desktop:** Capture sourceUrl + clickable activity rows ([9c13ff2](https://github.com/nikrich/ghost-brain/commit/9c13ff2a6f080788a8676b3d3e3d829f69084952))
* **api+desktop:** Clickable "caught lately" captures on Today ([5808cb3](https://github.com/nikrich/ghost-brain/commit/5808cb35bddf88d0e522ef06fe8c169379f4ccfb))
* **api+desktop:** Clickable past-meetings rows ([80fea6a](https://github.com/nikrich/ghost-brain/commit/80fea6af2f968c620f0e3ec79842f47068139c95))
* **api+desktop:** Daily digest, semantic search, in-app markdown viewer ([9704b3f](https://github.com/nikrich/ghost-brain/commit/9704b3f783902fae2af3db8ff03cb2e965c09650))
* **api+desktop:** Setup screen + auto-record toggle ([a6ead24](https://github.com/nikrich/ghost-brain/commit/a6ead24ebfb215e8b187f5a6f10d018b01b0d4a2))
* **api+desktop:** Start/stop manual recordings end-to-end ([21688c6](https://github.com/nikrich/ghost-brain/commit/21688c6a8657818a3536c613f5d78c9db0787c4a))
* **desktop:** Add Content-Security-Policy meta tag ([3d74901](https://github.com/nikrich/ghost-brain/commit/3d74901f653ddac50c57ed850b11e834491409fd))
* **desktop:** App icon ([17f042d](https://github.com/nikrich/ghost-brain/commit/17f042d2fe097d7a4518b9241cab09f0bd0e7164))
* **desktop:** Capture inbox screen + extract Catch component ([94aa178](https://github.com/nikrich/ghost-brain/commit/94aa1781b84693bd85634532b48666680fb0b506))
* **desktop:** Capture screen reads from sidecar ([81de4db](https://github.com/nikrich/ghost-brain/commit/81de4dbf6ebc781ea48bcf33d7e0ff76c493ac60))
* **desktop:** Connector logos for claude_code, jira, confluence, atlassian ([3e4cfa8](https://github.com/nikrich/ghost-brain/commit/3e4cfa8d6502f31a419e71a62983197aa4d33dfd))
* **desktop:** Connectors screen — list + detail ([b36a33a](https://github.com/nikrich/ghost-brain/commit/b36a33a38b46f952c9bddf27f722a2ff1046f0b5))
* **desktop:** Connectors screen reads from sidecar ([fc2cb7e](https://github.com/nikrich/ghost-brain/commit/fc2cb7ea3d4e36d74a98ccff311ae99aa0fa0eb9))
* **desktop:** Density toggle has real visual effect ([3bc9b82](https://github.com/nikrich/ghost-brain/commit/3bc9b822839c584371164cd4bf32d2bf56badbc0))
* **desktop:** ErrorBoundary wraps the App tree ([c1c6d1a](https://github.com/nikrich/ghost-brain/commit/c1c6d1a8b0c7658eb74b18ad8c6e501464c08d4d))
* **desktop:** Extend [@theme](https://github.com/theme) tokens to cover design's full scale ([8765369](https://github.com/nikrich/ghost-brain/commit/876536927565e39e927bb180faf06ca140555afb))
* **desktop:** Finalize Slice 1 — drop prototype, add README ([be830c4](https://github.com/nikrich/ghost-brain/commit/be830c48e5f619949ff73468b0519f8f83dba949))
* **desktop:** HiddenInset window chrome on macOS ([a6144c4](https://github.com/nikrich/ghost-brain/commit/a6144c4f4e094a93f57c3fb78a7c2a433b43239a))
* **desktop:** In-app scheduler with tray + background lifecycle ([7d8749a](https://github.com/nikrich/ghost-brain/commit/7d8749ab0b1fc70555a8d78e57b944a4e1c83b0a))
* **desktop:** Kind-aware toasts (info/success/error) ([160feb1](https://github.com/nikrich/ghost-brain/commit/160feb1fbee4d0756be7c4871655e6bd34324a10))
* **desktop:** Meetings history reads from sidecar ([33d4f50](https://github.com/nikrich/ghost-brain/commit/33d4f50e8ae1e0e84c02b41e59edbe1565a43bcb))
* **desktop:** Meetings screen with pre/live/post state machine ([fb52a37](https://github.com/nikrich/ghost-brain/commit/fb52a37645d88decf3f15d942919329864a59e5c))
* **desktop:** Native application menu ([4435168](https://github.com/nikrich/ghost-brain/commit/44351682610464fa046933ca16194295338563e1))
* **desktop:** Open external markdown links in the browser ([3e7a455](https://github.com/nikrich/ghost-brain/commit/3e7a4558b1ad2302139e1de4d5194067fa324c4e))
* **desktop:** Port shared primitives (Lucide, Ghost, Btn, Pill, Toggle, Panel, Eyebrow) ([a021c99](https://github.com/nikrich/ghost-brain/commit/a021c99b1f1143152dbd495802374e5782ccbbcd))
* **desktop:** Re-enable renderer sandbox ([9ffd0e7](https://github.com/nikrich/ghost-brain/commit/9ffd0e78710c406267f0214f59e3847e12cad6a3))
* **desktop:** React Query client + typed api wrapper ([a2e0c0a](https://github.com/nikrich/ghost-brain/commit/a2e0c0aa9924bcb9e9dacd1b14c478927118f5f0))
* **desktop:** React query hooks per endpoint ([908c167](https://github.com/nikrich/ghost-brain/commit/908c16759738ff15ad4c9e09d42b5b2a180fcc17))
* **desktop:** Scaffold electron-vite project, archive prototype ([96dd386](https://github.com/nikrich/ghost-brain/commit/96dd3869bf85af3a8230c6977593e4c3b86b9096))
* **desktop:** Settings screen with persistent display/vault settings ([8b4bf3b](https://github.com/nikrich/ghost-brain/commit/8b4bf3b238118ab5824af442376c73bcf1618bb0))
* **desktop:** Sidebar nav, top bar, status bar, toaster shell ([12bbba9](https://github.com/nikrich/ghost-brain/commit/12bbba966fc92d9a7274bd51274617e939f607d0))
* **desktop:** Sidecar class for Python subprocess lifecycle ([edc81b1](https://github.com/nikrich/ghost-brain/commit/edc81b120bd27de41cd53271d1c23c2fc6fe5313))
* **desktop:** Sidecar status store + setup screen ([503d34e](https://github.com/nikrich/ghost-brain/commit/503d34efddb0c8aaae1a610055195b4bf96eaea8))
* **desktop:** SkeletonRows / PanelEmpty / PanelError primitives ([5a427dc](https://github.com/nikrich/ghost-brain/commit/5a427dc94457b066798c956e67c3d77cb19ef48f))
* **desktop:** Spawn sidecar on app launch; wire api request IPC ([94880b8](https://github.com/nikrich/ghost-brain/commit/94880b8307f42d6924ff1c18a8bf6fad2ba31d65))
* **desktop:** Tailwind v4 with design-token [@theme](https://github.com/theme) ([23d31e2](https://github.com/nikrich/ghost-brain/commit/23d31e2cc032c576f4100345f36371004e4410a5))
* **desktop:** Today screen — dashboard, agenda, activity, suggestions ([5b43999](https://github.com/nikrich/ghost-brain/commit/5b4399913e7c458d578b602e6c99520f871ef23f))
* **desktop:** Today screen reads from sidecar ([3e17c54](https://github.com/nikrich/ghost-brain/commit/3e17c5497f9cd1c69d76fc33fe9d1a46aaac7e4b))
* **desktop:** Typed api bridge + sidecar control + api-types ([036bbe5](https://github.com/nikrich/ghost-brain/commit/036bbe5878116c4d0fee5215051ae6aeb5f052b7))
* **desktop:** Typed contextBridge + electron-store settings ([c933436](https://github.com/nikrich/ghost-brain/commit/c9334368f69f89ebede1dc9f24f94b2cda2f05d7))
* **desktop:** Typed HTTP forwarder to the sidecar ([d331a80](https://github.com/nikrich/ghost-brain/commit/d331a800b072206f8413e3b25d560b3826d69d2b))
* **desktop:** Typed mock data per screen ([e31f4d6](https://github.com/nikrich/ghost-brain/commit/e31f4d65140cd139b951af282342d91b3006f45c))
* **desktop:** Validate IPC handler inputs with zod ([51d97ec](https://github.com/nikrich/ghost-brain/commit/51d97ec729667a980dc3a2235a7020587f2706f3))
* **desktop:** Vault screen with real shell.openPath ([d8e4f2e](https://github.com/nikrich/ghost-brain/commit/d8e4f2e65001c7842a7da7be581f1072474008b7))
* **desktop:** Vendor official brand svgs for connector icons ([61f4d10](https://github.com/nikrich/ghost-brain/commit/61f4d109330cb302ff5c5858083351f31d3006d0))
* **desktop:** Window state persistence ([e6c40c9](https://github.com/nikrich/ghost-brain/commit/e6c40c92970538f4feca86f7902ccf6f88658e03))
* **desktop:** Wire all settings toggles and selects to real persistence ([42ad3dd](https://github.com/nikrich/ghost-brain/commit/42ad3dd064a9e577646e962a0fb8382d0c766367))
* **desktop:** Zustand stores (nav, settings, meeting, toast) ([5842754](https://github.com/nikrich/ghost-brain/commit/584275436625b88e66c92b543ea4b848e0f222db))


### Bug Fixes

* **api+desktop+gmail:** 404 capture detail, marketing leak, stub buttons ([4549321](https://github.com/nikrich/ghost-brain/commit/454932106fe6eeff27db8c9b356aedb0baf31606))
* **api+desktop:** Repair agenda/captures/meetings against real disk layout ([fa75083](https://github.com/nikrich/ghost-brain/commit/fa75083590edde146478fce96431c38ea4f39a90))
* **api+desktop:** Surface real captures + connectors that ran days ago ([58fd08c](https://github.com/nikrich/ghost-brain/commit/58fd08c3e6f58974ac8336b1038dc61226c32e54))
* **desktop:** Account section honest empty state ([4f04a9f](https://github.com/nikrich/ghost-brain/commit/4f04a9f59ac805525d407956beb1ec5bcb27fd81))
* **desktop:** Add @testing-library/dom peer dep so vitest can resolve it ([b52c12e](https://github.com/nikrich/ghost-brain/commit/b52c12e68c16c233a509673530d11258b0147db1))
* **desktop:** Align table headers with row data ([00cc384](https://github.com/nikrich/ghost-brain/commit/00cc3840c5c782bf78c95a8ac08f96ce1adc0725))
* **desktop:** Center page content on wide screens ([406787f](https://github.com/nikrich/ghost-brain/commit/406787f9fcd7f9da34c2e7aff9da34972b25af70))
* **desktop:** Introduce --neon-ink for readable neon-on-light text ([1aa5ae9](https://github.com/nikrich/ghost-brain/commit/1aa5ae976f71fa1985d70a637015089754f7c46d))
* **desktop:** Sidecar uses project venv python instead of PATH python3 ([94f8cd7](https://github.com/nikrich/ghost-brain/commit/94f8cd732cc101d271d18bbdb2ec54aa4fb4baab))
* **desktop:** Theme switching — use [@theme](https://github.com/theme) inline to preserve runtime cascade ([28ec9fc](https://github.com/nikrich/ghost-brain/commit/28ec9fc1a55f2a96bf1d549076c914a5fdeb06a0))
* **desktop:** Theme switching actually flips + readable neon on bone ([b2b322a](https://github.com/nikrich/ghost-brain/commit/b2b322a53fdbc01739a97482a7bbf039d5408117))
