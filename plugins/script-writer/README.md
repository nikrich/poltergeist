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
