# Changelog

## [0.8.0](https://github.com/nikrich/poltergeist/compare/v0.7.0...v0.8.0) (2026-07-07)


### Features

* feat(search): recency-aware ranking + days filter for time-anchored queries

### Bug Fixes

* fix(tests): skip recency ranking tests where numpy isn't installed
* fix(recorder): discard silent-recording transcripts instead of writing junk notes
* fix(scheduler): don't restore transient running flag from persisted state
* fix(desktop): lint-clean test mocks and remove stale eslint-disable

## [0.7.0](https://github.com/nikrich/poltergeist/compare/v0.6.0...v0.7.0) (2026-07-06)


### Features

* feat(brain-constellation): density-aware rendering; card owns note-open actions
* feat(desktop): vault screen hosts the brain constellation
* feat(desktop): BrainConstellation canvas component (ported from mockup)
* feat(desktop): pure constellation engine (camera, hit-test, adjacency)
* feat(desktop): useVaultGraph hook + graph types
* feat(api): GET /v1/vault/graph
* feat(api): vault graph builder (nodes by embedding, related/wikilink edges)
* feat(semantic): deterministic region palette
* feat(semantic): recompute 2-D layout on index refresh
* feat(semantic): 2-D projection of the embedding index (UMAP/PCA) + layout cache

### Bug Fixes

* fix(semantic): lazy numpy import so the API works without the [semantic] extra
* fix(brain-constellation): dedupe related list and close card on empty-canvas click
* fix(semantic): stable UMAP layout, skip redundant recompute, tolerate malformed layout.json
* fix(desktop): satisfy strict indexed access in hitTest

## [0.6.0](https://github.com/nikrich/poltergeist/compare/v0.5.0...v0.6.0) (2026-07-06)


### Features

* **plugins:** sidecar bridge — plugins can call the local `/v1/*` API through the host ([#67](https://github.com/nikrich/poltergeist/issues/67))
* **import:** Atlassian (Jira/Confluence) import is now an installable plugin — the tab is no longer in core. Install it from Plugins → git URL `https://github.com/nikrich/poltergeist-atlassian-import` if you use Atlassian ([#67](https://github.com/nikrich/poltergeist/issues/67))

## [0.5.0](https://github.com/nikrich/poltergeist/compare/v0.4.1...v0.5.0) (2026-07-06)


### Features

* **plugins:** runtime plugin system — install plugins from a folder or git URL, crash-isolated loader, path-contained `plugin://` renderer host, and a Plugins management screen ([#65](https://github.com/nikrich/poltergeist/issues/65))

## [0.4.1](https://github.com/nikrich/poltergeist/compare/v0.4.0...v0.4.1) (2026-07-02)


### Features

* **chat:** the chat agent can now use WebFetch + WebSearch to pull in public/external information ([#61](https://github.com/nikrich/poltergeist/issues/61))

## [0.4.0](https://github.com/nikrich/poltergeist/compare/v0.3.10...v0.4.0) (2026-07-01)


### Features

* **chat:** Accept Excel (.xlsx) attachments (openpyxl extraction) ([#59](https://github.com/nikrich/poltergeist/issues/59)) ([5dba9e1](https://github.com/nikrich/poltergeist/commit/5dba9e1093f4fab08014c766a397af2f4303771a))
* **chat:** File attachments in chat (Slice 1 — text/markdown/code) ([#56](https://github.com/nikrich/poltergeist/issues/56)) ([3c4ca7d](https://github.com/nikrich/poltergeist/commit/3c4ca7d67f6b36d29b8e7e89d30648dc44773f88))
* **chat:** Image attachments in chat (Slice 3 — vision caption) ([#58](https://github.com/nikrich/poltergeist/issues/58)) ([a4679bc](https://github.com/nikrich/poltergeist/commit/a4679bc61f6687b31c11490afa1d819c41aeb298))
* **chat:** PDF/Word attachments in chat (Slice 2) [stacked on [#56](https://github.com/nikrich/poltergeist/issues/56)] ([#57](https://github.com/nikrich/poltergeist/issues/57)) ([db418a4](https://github.com/nikrich/poltergeist/commit/db418a429031662ab808b117bdd58c190cd2f1b9))
* **docs:** In-chat doc generation (styled HTML → PDF) ([#60](https://github.com/nikrich/poltergeist/issues/60)) ([ea6a89b](https://github.com/nikrich/poltergeist/commit/ea6a89b757e77895ecdfeef785f5b18b11a15c28))


### Chores

* Release 0.4.0 ([d4f975d](https://github.com/nikrich/poltergeist/commit/d4f975d39fda7f4a5d330d334c98b0b88e7a0533))

## [0.3.10](https://github.com/nikrich/poltergeist/compare/v0.3.9...v0.3.10) (2026-06-25)


### Bug Fixes

* **jots:** Grant claude file access to the image dir for vision extraction ([#50](https://github.com/nikrich/poltergeist/pull/50))

## [0.3.9](https://github.com/nikrich/poltergeist/compare/v0.3.8...v0.3.9) (2026-06-24)


### Features

* **search:** Show last-indexed time + manual reindex in Settings ([#48](https://github.com/nikrich/poltergeist/issues/48)) ([8b8733d](https://github.com/nikrich/poltergeist/commit/8b8733d079951fdca12dc07e669e0d2ebaa7cafc))

## [0.3.8](https://github.com/nikrich/poltergeist/compare/v0.3.7...v0.3.8) (2026-06-24)


### Features

* **jots:** Expose gb.assets bridge (write + toUrl) ([a308ea2](https://github.com/nikrich/poltergeist/commit/a308ea2154dce8975bbf6dd5b84a9f6f1707fe0a))
* **jots:** Final visual polish + inline image CSS ([ee9202b](https://github.com/nikrich/poltergeist/commit/ee9202b8c8a271c394fcc64496c4c7c0c172853c))
* **jots:** Formatting toolbar ([869ca25](https://github.com/nikrich/poltergeist/commit/869ca2515256b4a3b246cc29d5fff7aacb3d5de1))
* **jots:** Gbasset:// protocol + asset write IPC ([ea3c044](https://github.com/nikrich/poltergeist/commit/ea3c0446d3e236c936a2ebbc023eb4cab27f6aaf))
* **jots:** Grant camera permission + NSCameraUsageDescription + entitlement ([a1af494](https://github.com/nikrich/poltergeist/commit/a1af494a0203f424c88f243af320d21dbd1c56d4))
* **jots:** Inline image node with gbasset rendering + md round-trip ([d152886](https://github.com/nikrich/poltergeist/commit/d1528861d514198868afeef639778fb51a6abd73))
* **jots:** Neon extract-callout rendering (md-portable) ([387a552](https://github.com/nikrich/poltergeist/commit/387a55265f741c05735962c462c54dc8dca4cae0))
* **jots:** Open webcam from toolbar, slash, and top bar ([df2346d](https://github.com/nikrich/poltergeist/commit/df2346df385a64732d73372dddae213ae2cd8896))
* **jots:** Paste/drop image insertion ([08fcbd5](https://github.com/nikrich/poltergeist/commit/08fcbd5962c41640d96431cf057cffcc758411f3))
* **jots:** Slash command menu ([7c1c299](https://github.com/nikrich/poltergeist/commit/7c1c299bb52d1619787bb22283ab3747007bfd35))
* **jots:** Thumbnails in the jot tree ([c7cd7e4](https://github.com/nikrich/poltergeist/commit/c7cd7e4fa0a869ea9c31dc52b1ee8de1f85692b7))
* **jots:** Trigger vision extraction after photo insert ([3aa568d](https://github.com/nikrich/poltergeist/commit/3aa568d360228d3bad52d18d55cef04699296e7e))
* **jots:** Webcam capture modal ([db2d1bf](https://github.com/nikrich/poltergeist/commit/db2d1bfbcbac3152d4bcc78b3928e5e81106f76b))
* **jots:** WYSIWYG editor, webcam capture, vision extraction ([f6ddc43](https://github.com/nikrich/poltergeist/commit/f6ddc43dbf9f1a9b90e4f0e5259889490766ea48))


### Bug Fixes

* **jots:** Allow gbasset: scheme in renderer CSP so vault images load ([0953f00](https://github.com/nikrich/poltergeist/commit/0953f00254069788c2fed42a3f70b1a9652f388a))
* **jots:** Drop unused join import in assets.ts ([31f919f](https://github.com/nikrich/poltergeist/commit/31f919f49bf0cdd780299563761811a469ae380a))
* **jots:** Guard webcam getUserMedia race + restore test prototype stubs ([2275ded](https://github.com/nikrich/poltergeist/commit/2275ded69e601707095929bb16dc3b041980d95f))
* **jots:** Reconcile editor after extraction (prevent callout overwrite); empty vision result -&gt; extracted=false ([d1429e5](https://github.com/nikrich/poltergeist/commit/d1429e56cb7cdef39659c4aa9c593cc16e43c309))
* **jots:** Require jotId prop + cover image-insert failure path ([bdb613f](https://github.com/nikrich/poltergeist/commit/bdb613f718f3756dd210654520292148aaf225e1))
* **jots:** Satisfy noUncheckedIndexedAccess in CSP test ([d67400a](https://github.com/nikrich/poltergeist/commit/d67400a626264dc60bd4797868f101b237da4a90))

## [0.3.7](https://github.com/nikrich/poltergeist/compare/v0.3.6...v0.3.7) (2026-06-22)


### Bug Fixes

* **sidecar:** Gate runtime descriptor on a singleton lock so a second instance can't orphan it ([#44](https://github.com/nikrich/poltergeist/pull/44)) ([bc8d7dc](https://github.com/nikrich/poltergeist/commit/bc8d7dc))

## [0.3.6](https://github.com/nikrich/poltergeist/compare/v0.3.5...v0.3.6) (2026-06-19)


### Bug Fixes

* **import:** Surface Confluence folders so folder-nested pages are importable ([#42](https://github.com/nikrich/poltergeist/issues/42)) ([b91d698](https://github.com/nikrich/poltergeist/commit/b91d6985d944b44b259a46c3ad8d1094bb2d02ad))

## [0.3.5](https://github.com/nikrich/poltergeist/compare/v0.3.4...v0.3.5) (2026-06-18)


### Bug Fixes

* **chat:** Bundle the `mcp` library so the packaged `ghostbrain-api mcp` server starts — it was crashing with `ModuleNotFoundError: No module named 'mcp'`, so vault chat could never connect. `mcp` moved into the `[api]` extra the build installs, and its package metadata is now shipped (FastMCP reads `version("mcp")` at import) ([94cc3e3](https://github.com/nikrich/poltergeist/commit/94cc3e3))

## [0.3.4](https://github.com/nikrich/poltergeist/compare/v0.3.3...v0.3.4) (2026-06-18)


### Bug Fixes

* **chat:** Start the MCP server before importing the api app so packaged vault chat connects — the bundled `ghostbrain-api mcp` no longer eagerly imports the full route tree before its MCP handshake ([fff11e8](https://github.com/nikrich/poltergeist/commit/fff11e8b7aa506f01858a5bc75e248230f338f3c))

## [0.3.3](https://github.com/nikrich/poltergeist/compare/v0.3.2...v0.3.3) (2026-06-18)


### Bug Fixes

* **chat:** Pin MCP config so vault chat can't leak the user's global MCP servers or wedge on an unclearable permission prompt; bundled `ghostbrain-api` now serves the MCP tools via an `mcp` subcommand so packaged chat has vault tools ([5b833e2](https://github.com/nikrich/poltergeist/commit/5b833e2eabbbbbbbb382fa030f3d0f8be844f4d8))

## [0.3.2](https://github.com/nikrich/poltergeist/compare/v0.3.1...v0.3.2) (2026-06-17)


### Bug Fixes

* Recorder: desktop Stop button now works — is_running() treats zombie PIDs as dead, and a single-instance lock stops a second sidecar double-recording meetings ([dcfb3d8](https://github.com/nikrich/poltergeist/commit/dcfb3d8877fe7e86f2433ae8fb03978fc2f40b0e))
* Deb packaging metadata — author, homepage, description ([f8865fb](https://github.com/nikrich/poltergeist/commit/f8865fb52d4b3fa86c9a29795be4ed9e30d49168))
* Deb packaging metadata for linux release builds ([1b03f40](https://github.com/nikrich/poltergeist/commit/1b03f40512b5c305ae972e877e9ce64bae774aff))
* Lint errors blocking mac/linux release builds ([d8d2d69](https://github.com/nikrich/poltergeist/commit/d8d2d69d5627f796d0b34dc49d7b68c1e179b7d6))
* Lint errors blocking mac/linux release builds ([e03d6e3](https://github.com/nikrich/poltergeist/commit/e03d6e391fc2473c8ee545c7a093bb459b7dede6))

## [0.3.1](https://github.com/nikrich/poltergeist/compare/v0.3.0...v0.3.1) (2026-06-10)


### Features

* Atlassian import — in-app Confluence/Jira picker with bulk import ([c201daf](https://github.com/nikrich/poltergeist/commit/c201daf4e1bd97d87340f17f8282017925ea082b))
* Atlassian import — land PR [#22](https://github.com/nikrich/poltergeist/issues/22) onto main ([77ca8c8](https://github.com/nikrich/poltergeist/commit/77ca8c8773264a42624e31bb9bcfd2cfffe10b1f))
* **chat:** Chat screen — conversation list, streaming thread, composer ([df8df16](https://github.com/nikrich/poltergeist/commit/df8df168bdf9a95d9fc8778ed96f66f01e4b4a36))
* **chat:** Conversation query/mutation hooks ([94132b7](https://github.com/nikrich/poltergeist/commit/94132b7ebb9e008a44f6d3a5d820afa322b66395))
* **chat:** PATCH/DELETE support through the api bridge ([75e6b82](https://github.com/nikrich/poltergeist/commit/75e6b829a082ad33d59fdcf1067b9f3a65aa2b45))
* **chat:** Renderer streaming state store ([0b79649](https://github.com/nikrich/poltergeist/commit/0b796498122612d0b0c0dab6a8229b65fc8d6829))
* **chat:** Replace AskPanel with the chat screen (⌘K opens chat) ([9dc8faf](https://github.com/nikrich/poltergeist/commit/9dc8fafa460d02dd1621d2aebe5a69481f165079))
* **chat:** Retry button on turn errors ([901180f](https://github.com/nikrich/poltergeist/commit/901180fec9191e21989c7e02f4f83c087c19dbb9))
* **chat:** SSE relay main↔renderer with per-conversation abort ([9de360c](https://github.com/nikrich/poltergeist/commit/9de360c9ae5fbd88b98c5af848c3013076eb561d))
* **desktop:** 12-week activity heatmap tile on today dashboard ([bd60c3c](https://github.com/nikrich/poltergeist/commit/bd60c3c907151ecfe3dcab97942a14f4a54cd055))
* **desktop:** Activity screen with year heatmap, day log, source chips ([a20626b](https://github.com/nikrich/poltergeist/commit/a20626bd50d32dcd50b7047a5a7a959590dbacc6))
* **desktop:** ActivityHeatmap component with 5 intensity buckets ([987fc2d](https://github.com/nikrich/poltergeist/commit/987fc2d8a43f917390a49f10c92995588568c524))
* **desktop:** API hooks for jot list/get/create/update/route/delete ([d5e4169](https://github.com/nikrich/poltergeist/commit/d5e416920063a76707e37e08a4d4241d0d9ad023))
* **desktop:** Copy-formatted — selection-aware HTML+markdown clipboard with ⌘⇧C ([3e837f7](https://github.com/nikrich/poltergeist/commit/3e837f7fa0bb18206a157cfa64dd5802928bcb80))
* **desktop:** Editable vault note viewer — PATCH by path + synced-note warning chip ([e6d642c](https://github.com/nikrich/poltergeist/commit/e6d642c72274c671570697aeb654ff3f579a8f63))
* **desktop:** Gb:clipboard:write-rich IPC — html + markdown clipboard flavours ([5d6008b](https://github.com/nikrich/poltergeist/commit/5d6008b46e8479c3e9ebac7dc677ed598d77196a))
* **desktop:** Global Alt+J hotkey + jot overlay window lifecycle ([0a19902](https://github.com/nikrich/poltergeist/commit/0a1990205128a1193bb8dd620358e1d4e6ee9152))
* **desktop:** Heatmap api types + useActivityHeatmap/useActivityForDate hooks ([be3679e](https://github.com/nikrich/poltergeist/commit/be3679ef1fb0c8837539b5431d223c7a3304d707))
* **desktop:** Import api types, ApiError with status, import hooks ([50e67e6](https://github.com/nikrich/poltergeist/commit/50e67e601c5886ca1098f611fa1c01304157bb00))
* **desktop:** Import screen — tabs, checkbox lists, search, selection bar, progress ([f8b7f9a](https://github.com/nikrich/poltergeist/commit/f8b7f9ad3cf83d02b363c90bd2e37f78d8375787))
* **desktop:** Jot overlay renderer + preload bridge ([c6bf464](https://github.com/nikrich/poltergeist/commit/c6bf46471e58bc3abd6bf14bc618962c4484312f))
* **desktop:** JotEditor — CodeMirror markdown with 1s autosave ([168e34e](https://github.com/nikrich/poltergeist/commit/168e34e7cbd9359c3cf8914025b0400952cc3132))
* **desktop:** Jots screen — tree + editor + re-route + delete ([2a6f3d9](https://github.com/nikrich/poltergeist/commit/2a6f3d91a895d55162b3276c259d225745f487b1))
* **desktop:** Jots screen uses RichMarkdownEditor (CodeMirror stays as src mode) ([e21e157](https://github.com/nikrich/poltergeist/commit/e21e1578c24cd5403fec5c099befe6746a123c4d))
* **desktop:** JotTree component (context → month grouping) ([6bedd2a](https://github.com/nikrich/poltergeist/commit/6bedd2a383213d190870e16be21d99cd0fe98c19))
* **desktop:** RichMarkdownEditor — TipTap WYSIWYG with autosave + source toggle ([bb7b399](https://github.com/nikrich/poltergeist/commit/bb7b39904c344a342474477abb7a95ffd4ab6b2a))
* **desktop:** TipTap v2 stack + markdown round-trip fixture gate ([d67627e](https://github.com/nikrich/poltergeist/commit/d67627e1123a6a319b92eb906d20839e3ab578d9))
* **desktop:** Widen api-forwarder to PATCH/DELETE for jot mutations ([483ee07](https://github.com/nikrich/poltergeist/commit/483ee07a6f9f746f46c3c4e171272730801b23b1))
* GitHub-style activity heatmap — dashboard tile + activity screen ([1abad0c](https://github.com/nikrich/poltergeist/commit/1abad0c29b01b120cf687e0de9ac68791fc73e5e))
* Poltergeist chat — agentic multi-turn chat with the vault ([60a6096](https://github.com/nikrich/poltergeist/commit/60a6096cd8defe7ab41b831fd96d5e4787bcf323))
* Rich markdown editor (TipTap WYSIWYG) + copy-formatted for Slack/Confluence/Teams ([2f475d7](https://github.com/nikrich/poltergeist/commit/2f475d70c7aa9fd5b20c57099049ac9df9fd705c))
* Wikilink click-to-navigate in rich editor + CI workflow ([cef1991](https://github.com/nikrich/poltergeist/commit/cef199168f02154c9f1648ff29abd7c8f2f9478d))


### Bug Fixes

* Activity feed shows ghost icon instead of broken image for internal sources ([b3a6605](https://github.com/nikrich/poltergeist/commit/b3a6605f213db50b8fe1f255c23d85047ede4370))
* **chat:** Abort chat stream on window destroy; surface error detail ([50d4c8f](https://github.com/nikrich/poltergeist/commit/50d4c8f4c2742d35a9f0173248c4aefde5d06686))
* **chat:** Let gb-note: wikilink hrefs through react-markdown's sanitizer ([f4256a5](https://github.com/nikrich/poltergeist/commit/f4256a5a36d29be5a057316635ea465e9e93abdb))
* **chat:** Stop button + window close also stop the sidecar turn ([ba27734](https://github.com/nikrich/poltergeist/commit/ba27734e902876b649fbb524127fc111f5b12f36))
* Close function/interface bodies broken by rebase conflict seams ([9780478](https://github.com/nikrich/poltergeist/commit/97804782a4ee57fbd22a4e2a5a67f546cf7c71b8))
* **desktop:** Activity feed icon — ghost fallback for sourceless svgs + dash/underscore asset mapping ([68b44a8](https://github.com/nikrich/poltergeist/commit/68b44a876dd14b2c133bb24f50939b82297fced8))
* **desktop:** Cap heatmap cells at 18px and centre the grid; tile shows 26 weeks ([8bb2c9b](https://github.com/nikrich/poltergeist/commit/8bb2c9b426b1f28e75f562a583ff95a083233411))
* **desktop:** Fluid full-width heatmap — cells scale to container, squares kept via aspect-ratio ([1dad839](https://github.com/nikrich/poltergeist/commit/1dad839bb093a54bad068d777a9bb78fbfada044))
* **desktop:** Harden wikilink regex against malformed nesting + second-link test ([1b2b70e](https://github.com/nikrich/poltergeist/commit/1b2b70e25823f09f7ad7a67b86f4dfe948325754))
* **desktop:** Restore list markers in gb-prose — Tailwind preflight strips list-style ([77717c1](https://github.com/nikrich/poltergeist/commit/77717c1531937281bf28118cbe581ea694e5ebd2))
* **editor:** Restore wikilink click-to-navigate in RichMarkdownEditor ([d37be12](https://github.com/nikrich/poltergeist/commit/d37be127cf4dfcd2f51f1943288814dcaf277198))
* **jots:** Auto-route on leave — new-button jots were routed on placeholder content and never again ([e3b9302](https://github.com/nikrich/poltergeist/commit/e3b93026352e410939de189c884a32d74a1c3665))
* **merge:** Restore useDeleteConversation closing braces lost in merge resolution ([c29a178](https://github.com/nikrich/poltergeist/commit/c29a178fd97b7cb0a1c4ad49e88feadd838e11ad))

## [0.2.10](https://github.com/nikrich/poltergeist/compare/v0.2.9...v0.2.10) (2026-05-28)


### Bug Fixes

* **meeting-prep:** Make shouldFireNow test timezone-independent ([a478a06](https://github.com/nikrich/poltergeist/commit/a478a06039736e3bec6c73d6a68b67da1cc2d8c3))

## [0.2.9](https://github.com/nikrich/poltergeist/compare/v0.2.8...v0.2.9) (2026-05-25)


### Features

* **desktop:** Handle meetings:openPrep IPC to focus prep panel ([1eb7665](https://github.com/nikrich/poltergeist/commit/1eb7665c8429efe27f111ced64f7f68de4a31124))
* **desktop:** Install meeting-notifier on app start ([4f10c37](https://github.com/nikrich/poltergeist/commit/4f10c37b9a3e19297deeafd07619ec73d8eb29a2))
* **desktop:** Meeting-notifier poll loop + native Notification + click handler ([ed0f507](https://github.com/nikrich/poltergeist/commit/ed0f507238971378b93da55cf4bb2a918b437154))
* **desktop:** MeetingPrep component renders brief + related ([a15bb2a](https://github.com/nikrich/poltergeist/commit/a15bb2ab4efb4b55eb442aeb7e76fc1eb6c63b4d))
* **desktop:** Prep / RelatedItem / EventSnapshot types ([4811921](https://github.com/nikrich/poltergeist/commit/481192128e3966f4fe9454e9573c956b4311e665))
* **desktop:** Render UpcomingMeetings on the meetings screen ([fbd4fda](https://github.com/nikrich/poltergeist/commit/fbd4fda30a7e1f89afddfb401dd11a8f275716ac))
* **desktop:** Selected-event store for prep panel auto-expand ([88bf9e3](https://github.com/nikrich/poltergeist/commit/88bf9e34b9ed96dd647e67cce6e8e8ef8b10eb3c))
* **desktop:** ShouldFireNow predicate for meeting notifier ([2c2c403](https://github.com/nikrich/poltergeist/commit/2c2c4032adcef825c20cc2e85d1feede3d17c3a2))
* **desktop:** UpcomingMeetings list with inline prep expansion ([d9aa751](https://github.com/nikrich/poltergeist/commit/d9aa75115f6804b54b0905e45a8f8e984b9ae9f4))
* **desktop:** UseMeetingPrep + usePrewarmMeetingPrep hooks ([365596c](https://github.com/nikrich/poltergeist/commit/365596c8f61a15c9dca8a984311610f14c68cc3a))


### Bug Fixes

* **meeting-prep:** Allow default retry on useMeetingPrep ([4565c60](https://github.com/nikrich/poltergeist/commit/4565c60d6cce24a4926933a0fd2f565457bd479d))
* **meeting-prep:** Satisfy react/no-unescaped-entities in MeetingPrep copy ([175781b](https://github.com/nikrich/poltergeist/commit/175781bd4993330094920c4a8f8d732f77a15341))

## [0.2.8](https://github.com/nikrich/poltergeist/compare/v0.2.7...v0.2.8) (2026-05-21)


### Bug Fixes

* **sidecar:** call `multiprocessing.freeze_support()` at the top of `ghostbrain/api/__main__.py` so the PyInstaller bundle doesn't fork-bomb itself. The bundled ML stack (`torch`, `transformers`, `sentence-transformers`, `joblib`) touches `multiprocessing` at module load, and macOS defaults to the `spawn` start method, which re-execs `sys.executable -B -S -I -c "from multiprocessing.resource_tracker import main; main(N)"` to launch the resource_tracker helper. The PyInstaller bootloader silently ignores `-c`, so the "helper" was running a full second uvicorn + scheduler on a new random port — which then imported the same ML stack and spawned its own "helper", recursively. By morning there were ~10 orphaned `ghostbrain-api` processes, each still firing scheduler jobs and shelling out to `claude -p`, swamping CPU and RAM. PyInstaller's runtime hook installs a `_freeze_support` that detects the spawn argv and `sys.exit()`s in the helper — but only if `freeze_support()` is actually called. Adding the call short-circuits the helper subprocess immediately and stops the runaway re-spawn. In dev (non-frozen) Python it's a no-op, so the dev path is unaffected.

## [0.2.7](https://github.com/nikrich/poltergeist/compare/v0.2.6...v0.2.7) (2026-05-20)


### Features

* **answer:** audit-log every `/v1/answer` call with the query text, source paths actually loaded, answer length, error string, and duration. When the user says "the vault isn't finding anything" we now have one log line per call instead of guessing phrasings — same fix shape as the Slack fetch_debug sentinel, applied to the chat path.


### Bug Fixes

* **scheduler:** skip-if-already-running on `_invoke`. The v0.2.6 fetch_debug log showed two concurrent slack syncs running in parallel (manual sync + cron loop firing on the same job), each scoring 8 batches of Slack messages through `claude -p` separately. The second caller now returns a fast no-op `skipped_reason="already_running"` and the in-flight run keeps going.
* **search:** path-prefix boost (+0.08) for notes under `*/transcripts/*`. Pure cosine ranking was putting content-light calendar event notes above the actual transcripts, and on phrasings like "yesterday's workshop" the transcripts were falling out of the top-K entirely because the word "yesterday" lexically anchors to other notes that literally say "yesterday". With the boost, workshop transcripts move from #5/#6 to #1/#2 on the user's actual reported query.


### Chores

* **slack:** strip the v0.2.3 + v0.2.4 diagnostic sentinels (`allowlist_debug.log`, `fetch_debug.log`) now that v0.2.6 confirmed the SSL fix works end-to-end. ~150 lines of traced wrapping back to clean shape.

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
