# LLM providers

Poltergeist needs an LLM for routing, extraction, digests, `/v1/answer`, and
desktop chat. By default that's the `claude` CLI, billed to your Claude
subscription. You can point it at OpenAI's Codex CLI (ChatGPT subscription),
Google's Gemini CLI (Google account), or a local OpenAI-compatible server
(Ollama, LM Studio) instead. Every call site — the worker, digests, `/v1/answer`,
and desktop chat — runs on whichever provider is active; nothing else about
Poltergeist changes.

## Pick a provider

The `llm:` block lives in `<vault>/90-meta/config.yaml`. Bootstrap seeds it
commented out, which means `claude` (unchanged behavior):

```yaml
llm:
  provider: claude        # claude | codex | gemini | openai_http
  models:                 # per-tier overrides; null = provider default
    fast: null
    balanced: null
    quality: null
  openai_http:
    base_url: http://127.0.0.1:11434/v1   # Ollama; LM Studio is http://127.0.0.1:1234/v1
    api_key_env: OPENAI_API_KEY           # read only when base_url is not localhost
```

You can also edit the same settings from the desktop app: **Settings → AI
provider**. It shows a diagnostics row (the same probe `poltergeist doctor`
runs) with a re-check button, and for `openai_http` a base URL field plus
three model pickers populated from whatever the server lists. The chat
header carries a provider switcher too — every provider is listed, the ones
whose probe failed are disabled with the reason in the label, and picking a
different one switches the active provider starting with the next turn.
Either way you're editing the same `config.yaml`; the sidecar's config file
is the single source of truth and the desktop just mirrors it through
`GET`/`PUT /v1/settings/llm`.

### Tiers

Every call site asks for one of three tiers, not a model name — `fast`,
`balanced`, or `quality`. Each provider maps its own models to those tiers,
so switching providers doesn't require touching any other config:

| provider | fast | balanced | quality |
|---|---|---|---|
| `claude` | `haiku` | `sonnet` | `opus` |
| `codex` | `gpt-5-mini` | `gpt-5` | `gpt-5` (reasoning effort set to high) |
| `gemini` | `gemini-2.5-flash` | `gemini-2.5-pro` | `gemini-2.5-pro` |
| `openai_http` | none by default — pick a model for all three tiers, or the doctor check fails |

`llm.models.fast` / `.balanced` / `.quality` override any provider's default
for that tier. Local models (`openai_http`) have no built-in defaults at
all: `poltergeist doctor` fails until all three tiers name a model your
server actually serves.

### Aliases

Poltergeist's config has always used the Claude model names `haiku`,
`sonnet`, and `opus` in a handful of places — `worker.router_model`,
`worker.extractor_model`, `worker.digest_model`, `worker.profile_model`, and
chat's default model. Those keys keep working unchanged: they're accepted as
synonyms for `fast`, `sonnet` for `balanced`, and `opus` for `quality`. On a
non-Claude provider, `router_model: haiku` still means "run routing on
whichever model this provider maps to its fast tier" — it does not force
Claude. An unrecognized model name (anything other than the three tier names
or the three aliases) is a configuration error.

## Claude

The default provider — unchanged from before this feature existed. Batch
calls run `claude --print`, chat runs `claude --print --output-format
stream-json`, both billed to your Claude subscription login.

- **Install / sign in:** the `claude` CLI on PATH, logged in (`claude
  login`).
- **What the doctor checks:** `claude` is on PATH and `claude --version`
  succeeds.
- **Limitations:** none — this is the code path Poltergeist has always used.

## Codex

Runs batch and chat calls through OpenAI's Codex CLI, billed to your ChatGPT
subscription (no separate API key).

- **Install / sign in:** `npm i -g @openai/codex`, then `codex login`
  (opens a browser to your ChatGPT account).
- **What the doctor checks:** `codex` is on PATH and `codex login status`
  exits 0.
- **Limitations:**
  - **No images.** `codex exec --json` hangs when given `--image`, so a
    batch call with `image_paths` fails immediately with a clear error
    instead of hanging. The one caller that can pass images (attachment
    captions) already treats a failed caption as "no caption," so this is
    silent to the end user.
  - **No token streaming.** `codex exec` in non-interactive mode does not
    stream partial text — the whole reply arrives at once, in a single
    `item.completed` / `agent_message` event, once Codex is done. The chat
    UI shows it as one `delta` event rather than a token-by-token stream.

Override the binary with `GHOSTBRAIN_CODEX_BIN` if `codex` isn't the one on
your PATH.

## Gemini

Runs batch and chat calls through Google's Gemini CLI, billed to your Google
account (OAuth, an API key, or Vertex AI — whatever `gemini`'s own sign-in
already uses).

- **Install / sign in:** `npm install -g @google/gemini-cli`, then run
  `gemini` once and sign in (`/auth`), or set `GEMINI_API_KEY`.
- **What the doctor checks:** `gemini` is on PATH, and either
  `GEMINI_API_KEY` is set or `~/.gemini/settings.json` records an auth type
  (`oauth-personal`, `gemini-api-key`, or `vertex-ai`).
- **Limitations:**
  - **JSON output is best-effort.** For structured (schema) requests, the
    schema is embedded in the prompt asking Gemini to reply with only JSON.
    If the first reply doesn't parse, Poltergeist retries once with a
    stricter "output ONLY the JSON object" instruction; if that also fails,
    the call errors out the same way a parse failure on any provider does.
  - **Resuming a chat session depends on the installed CLI.** Poltergeist
    checks once per `gemini` binary whether its `--help` output advertises
    `--resume`. Newer CLIs use it directly; on an older CLI that doesn't
    support it, a resumed conversation instead gets the prior turns prefixed
    into the prompt as a transcript — the same fallback used when a Claude
    session fails to resume.

Override the binary with `GHOSTBRAIN_GEMINI_BIN` if `gemini` isn't the one
on your PATH.

## Local (Ollama, LM Studio, or any OpenAI-compatible server)

Talks HTTP directly to a server you're already running — no subscription,
no CLI, free. This is the `openai_http` provider; the desktop calls it
"local."

- **Install / sign in:** start Ollama (`http://127.0.0.1:11434/v1`) or LM
  Studio (`http://127.0.0.1:1234/v1`) and pull/load at least one model
  (`ollama pull qwen3`, for example). Set `llm.openai_http.base_url` if
  you're not using Ollama's default port.
- **What the doctor checks:** `GET {base_url}/models` answers, and the
  models configured for `fast`, `balanced`, and `quality` are all set and
  all present in that list. Unlike every other provider, `openai_http` has
  no default models — you must name one for each tier yourself, in Settings
  → AI provider or `llm.models` in `config.yaml`.
- **Limitations:**
  - **All three tiers must be configured explicitly** and must name a model
    the server actually lists; there's nothing to fall back to.
  - **Vault tools run in-process, not over MCP.** Every other provider's
    chat driver reaches Poltergeist's vault tools by spawning the
    `ghostbrain-api mcp` server as a real MCP server. The local driver has
    no MCP client, so it runs its own tool-call loop instead: it sends the
    four vault tools (`poltergeist_search`, `poltergeist_get_note`,
    `poltergeist_ask`, `poltergeist_write_doc`) as OpenAI-style function
    definitions, and when the model asks to call one, Poltergeist executes
    it directly against the vault and feeds the result back as a tool
    message — up to 8 rounds per turn. The descriptions the model sees are
    identical to what the MCP server would give it.
  - **No user-defined MCP servers.** Only the four vault tools are
    available locally; the MCP servers you've opted into from
    `~/ghostbrain/mcp-servers.json` are a Claude/Codex/Gemini-only feature
    in this release.
  - **Ollama uses `/api/chat`, not `/v1/chat/completions`, for structured
    output.** When a JSON schema is requested and the server turns out to
    be Ollama (detected by probing `/api/tags`), Poltergeist sets `format:
    <schema>` on Ollama's native `/api/chat` endpoint instead, since that's
    the path Ollama actually enforces the schema on.

## Chat and vault tools

How a chat turn reaches Poltergeist's vault tools depends on the provider:

- **Claude** spawns `claude --print --output-format stream-json` with the
  Poltergeist vault MCP server (the `ghostbrain-api mcp` binary) passed as
  an MCP server argument, plus any servers you've opted into from
  `~/ghostbrain/mcp-servers.json`.
- **Codex** generates a fresh, isolated `CODEX_HOME` at
  `~/ghostbrain/run/llm/codex` on every turn, containing a `config.toml`
  with `[mcp_servers.poltergeist]` (the vault MCP server, `required =
  true`) and one `[mcp_servers.<name>]` block per opted-in user server,
  `sandbox_mode = "read-only"`, and `approval_policy = "never"`. Your
  ChatGPT login is reused by symlinking `auth.json` from your real
  `~/.codex/auth.json` into that run directory — the file itself is never
  copied or edited.
- **Gemini** generates a fresh per-turn workspace at
  `~/ghostbrain/run/llm/gemini`, containing a `.gemini/settings.json` with
  an `mcpServers` block (the vault server plus any opted-in servers, each
  `trust: true`) and your auth type copied from your real
  `~/.gemini/settings.json`. `gemini` runs with that workspace as its
  working directory so it picks up the generated settings file instead of
  your real one.
- **Local** models don't spawn an MCP server at all — see "Vault tools run
  in-process" above.

In every case, **`~/.codex` and `~/.gemini` — your real CLI configuration —
are never written to.** Poltergeist only ever reads your existing login
(symlinking or copying just the auth type/token) into a disposable run
directory it regenerates on every turn.

`allowed_tools` semantics don't change with the provider: vault tools are
always available; your opted-in MCP servers from `mcp-servers.json` ride
along on Claude, Codex, and Gemini, and never on local.

## Troubleshooting

Run `poltergeist doctor`. It reports an `llm-provider` row: `ok` names the
active provider and its three tier models
(`fast=<model> balanced=<model> quality=<model>`); `fail` gives a one-line,
provider-specific reason — the CLI isn't installed, isn't signed in, or (for
local) the server isn't answering or is missing a model — plus a fix
(the install/login command, or "set it in Settings → AI provider").

If the active provider isn't usable, `/v1/answer` returns an HTTP 412 with
that same reason as its body. Desktop chat can't return an HTTP status once
it's already streaming, so it surfaces the identical reason as an `error`
event in the chat stream instead — you'll see it inline in the conversation
rather than as a failed request.

If you just fixed the provider (signed in, started Ollama, pulled a model)
and doctor or chat still reports it as down, wait up to a minute: the probe
result is cached for 60 seconds to avoid re-probing on every request, and
clears immediately if you change `llm.provider` (or any other `llm.*`
setting) from Settings.
