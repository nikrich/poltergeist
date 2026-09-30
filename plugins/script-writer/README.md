# Script Writer

A screenplay editor for Poltergeist. Write in plain [Fountain](https://fountain.io) while the page formats itself as you type, then export an industry-standard PDF.

## Writing

| Key | Does |
|---|---|
| Tab / Shift-Tab | Cycle the current line: Action → Character → (Parenthetical) → Transition → Scene heading |
| Enter | Next logical element: heading → action, character → dialogue, dialogue → character, transition → heading. Enter on an empty line returns to action. |
| Shift-Enter | New line within the same element |
| ⌘1–⌘7 | Scene heading, Action, Character, Parenthetical, Dialogue, Transition, Centered |
| ⌘S | Save now (autosaves 1.5 s after you stop typing) |
| ⌘⇧F | Focus mode (dims everything but the current paragraph; typewriter scrolling) |

Autocomplete offers `INT./EXT.` prefixes, known locations, `DAY/NIGHT/…`, character names, and `(V.O.)/(O.S.)/(CONT'D)`.

## Formatting

Use the formatting bar above the page:
- The **element dropdown** shows the current line's element and changes it (the same as Tab or ⌘1–7).
- **B / I / U** wrap the selection in bold, italic or underline (⌘B / ⌘I / ⌘U). They unwrap it if it's already wrapped.
- **+ Scene** starts a new scene after the one you're in.

You can also type Fountain directly:
- `**bold**`, `*italic*`, `_underline_`
- `>THE END<` for centered text
- `===` for a page break
- `[[note]]` for a note that doesn't print

## AI co-writer (⌘K)

Everything uses the AI provider you've set up in Poltergeist.

- **Ask.** It searches your vault, starting with this script's project folder, then the whole context. It answers with clickable `[n]` citations to your notes. Each script keeps its own conversation.
- **Actions.** Continue scene, Rewrite (tighter, funnier, darker, more subtext, or your own direction), Punch up dialogue, Scene from beat, and Continuity check. They work on the selection, or on the scene at the cursor. Suggestions appear in the script as an Accept / Insert / Reject block, and editing that text cancels the suggestion.
- **Polish.** Polishes the whole script, scene by scene, with Formatting, Language, Tighten prose and Punch up dialogue passes. You review every change in one view and keep or drop each one. Apply is a single ⌘Z. A scene the AI mangled is kept as it was and flagged.

## Final Draft

Import `.fdx` files from the Library. Export `.fdx` from the Export menu.

## Where scripts live

Each script is a vault note in its project folder:
`20-contexts/<context>/projects/<project>/<title>.screenplay.md`. Frontmatter holds the title page and the body is Fountain, so scripts are searchable like any note. Put your research, bios and outlines in the same project folder.

If the backend is unreachable, saving retries automatically and your text is mirrored locally. The next time you open the script you'll be offered the unsaved draft.

## Output

Courier Prime 12pt, 1.5" / 1" margins, 54 lines per page. Pagination handles `(MORE)` / `(CONT'D)`, never ends a page on a scene heading, and has optional scene numbers. US Letter or A4. Export PDF or `.fountain`, and import `.fountain`.

The editor loads Courier Prime from the plugin. On older app versions, whose content security policy blocks plugin fonts, the editor falls back to Courier New with the same 10 cpi layout. PDF export always embeds Courier Prime.

Courier Prime is © Quote-Unquote Apps, SIL Open Font License (see `dist/fonts/OFL.txt`).

## Develop

    npm install && npm test && npm run build   # commit dist/
