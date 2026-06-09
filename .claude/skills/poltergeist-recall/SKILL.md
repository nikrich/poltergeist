---
name: poltergeist-recall
description: Use to connect Poltergeist (the ghostbrain second-brain) to Claude Code/Desktop over MCP, and to query the user's vault during work. Triggers include "connect Poltergeist to Claude", "set up the Poltergeist MCP", "query my second brain/vault from here", or any moment where recalling the user's own prior decisions, past incidents, or why something was built a certain way would help.
---

# Poltergeist Recall

Query the user's Poltergeist vault from Claude via the `poltergeist` MCP server.
Two jobs: **install** the connection, then **use** it well during work.

## Install / verify the MCP connection

1. **Check the entrypoint resolves.** Run `which ghostbrain-mcp`. If missing,
   the user hasn't `pip install`-ed the package into the active env — have them
   run `pip install -e ".[mcp]"` from the repo (or point the command at the
   venv that has it).

2. **Add the server to `.mcp.json`.** Ask the user: project scope
   (`./.mcp.json`, this repo only) or user scope (every project)? Then add:
   ```json
   { "mcpServers": { "poltergeist": { "command": "ghostbrain-mcp" } } }
   ```
   (Merge into existing `mcpServers` if the file already has entries.)

3. **Confirm the sidecar is running.** The MCP forwards to the desktop app's
   sidecar. Check `~/ghostbrain/run/sidecar.json` exists and its `pid` is alive.
   If not, tell the user to open the Poltergeist desktop app.

4. **Smoke-test.** After the MCP reconnects, call `poltergeist_search` with a
   throwaway query (e.g. "test"). A structured result or the clear
   "Poltergeist isn't running" message both confirm the wiring is correct.

## Using it during work

See `using.md` in this skill directory for when to reach for each tool and how
to fold recalled context into your work.
