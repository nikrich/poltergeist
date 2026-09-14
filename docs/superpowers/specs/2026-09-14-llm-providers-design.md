# LLM Providers — Design

**Status:** Approved in conversation 2026-09-14 (pending spec review)
**Origin:** Poltergeist only runs on Claude Code (`claude -p`). Users with a ChatGPT or
Gemini subscription, or a local model, cannot use it at all.

## Problem

Every LLM call in the sidecar shells out to `claude -p`:

- **Batch:** `ghostbrain/llm/client.py:run()` — 24 call sites (router, extractor, digests,
  relevance gates, transcript titles, meeting prep, reversal, profile diff, `/v1/answer`,
  attachment captions, docs assist, manual notes). It takes a Claude model alias
  (`haiku` / `sonnet` / `opus`), an optional JSON schema (`--json-schema`), a system
  prompt, images, a timeout, and a USD budget cap.
- **Chat:** `ghostbrain/llm/agent.py:run_chat_turn()` spawns
  `claude -p --output-format stream-json` with the Poltergeist vault MCP server (our own
  binary's `mcp` subcommand) and the user's opted-in servers from
  `~/ghostbrain/mcp-servers.json`, and parses the stream into a small event vocabulary
  the desktop renderer consumes: `session`, `delta`, `tool`, `done`, `error`, with a
  `session_id` for resume.
- The desktop has a dormant `llmProvider: local | anthropic | openai` setting that
  nothing reads.

Model choice is expressed as Claude aliases throughout `90-meta/config.yaml`
(`router_model: haiku`, `extractor_model: opus`, …).

## Goals

1. The whole pipeline and the desktop chat run on any of: Claude Code (unchanged),
   OpenAI via the Codex CLI on a ChatGPT subscription, Google via the Gemini CLI on a
   Google account, or a local OpenAI-compatible server (Ollama, LM Studio).
2. No call site changes: `run()` keeps its signature; the chat event vocabulary is
   unchanged; existing `config.yaml` model keys keep working.
3. The user's own CLI configuration (`~/.codex`, `~/.gemini`) is never modified.
4. Doctor and Settings tell the user whether the chosen provider is usable and why not.

## Non-goals (version one)

- Image input on Codex (`codex exec --json` hangs with `--image`; see Error handling).
- User-defined MCP servers on local models.
- Per-role model settings in the UI (per-role keys in `config.yaml` still work).
- Cost or budget caps on non-Claude providers (subscriptions have no per-call cap;
  local is free).
- Direct metered API keys for OpenAI or Anthropic. `openai_http` accepts an API key for
  a non-localhost base URL, which covers OpenRouter-style endpoints, but the UI does not
  promote it.

## Design

### 1. Provider protocol and dispatch

New package `ghostbrain/llm/providers/`:

```python
# ghostbrain/llm/providers/base.py
Tier = Literal["fast", "balanced", "quality"]

@dataclass
class CompletionRequest:
    prompt: str
    tier: Tier
    json_schema: dict | None = None
    system_prompt: str | None = None
    image_paths: list[str] | None = None
    timeout_s: int = 120
    budget_usd: float | None = None      # honored by claude only

@dataclass
class ChatRequest:
    prompt: str
    tier: Tier
    session_id: str | None               # resume token from a previous `session`/`done` event
    turn_key: str                        # for cancel_turn()
    system_prompt: str
    user_servers: list[dict]             # opted-in entries from mcp-servers.json
    history: list[dict] | None = None    # only the local driver needs it (no server-side sessions)

@dataclass
class ProviderProbe:
    ok: bool
    reason: str                          # one line, user-facing
    detail: dict                         # version, auth type, models, base_url …

class Provider(Protocol):
    id: str                              # "claude" | "codex" | "gemini" | "openai_http"
    def models(self) -> dict[Tier, str]: ...       # effective tier → model after config overrides
    def complete(self, req: CompletionRequest) -> LLMResult: ...
    def chat(self, req: ChatRequest) -> Iterator[dict]: ...   # yields renderer events
    def probe(self) -> ProviderProbe: ...
```

`ghostbrain/llm/providers/__init__.py:get_provider(cfg=None) -> Provider` reads
`llm.provider` from `config.yaml` (default `claude`) and instantiates the adapter with
its tier overrides. `client.run()` becomes:

```python
def run(prompt, *, model=DEFAULT_MODEL, json_schema=None, system_prompt=None,
        budget_usd=None, timeout_s=DEFAULT_TIMEOUT_S, image_paths=None) -> LLMResult:
    provider = get_provider()
    return provider.complete(CompletionRequest(prompt=prompt, tier=to_tier(model), ...))
```

`to_tier()` maps `haiku → fast`, `sonnet → balanced`, `opus → quality`, passes
`fast|balanced|quality` through, and raises `LLMError` for anything else. The Claude
adapter maps tiers back to aliases, so today's behavior is bit-identical on Claude.
`agent.run_chat_turn()` likewise becomes `get_provider().chat(ChatRequest(...))`;
`cancel_turn` / `kill_all_running` move to `providers/base.py` and every driver
registers its subprocess (or HTTP stream) there.

### 2. Configuration

`90-meta/config.yaml` gains an `llm` block (bootstrap seeds it commented; absent keys
default to Claude):

```yaml
llm:
  provider: claude            # claude | codex | gemini | openai_http
  models:                     # per-tier overrides; null = provider default
    fast: null
    balanced: null
    quality: null
  openai_http:
    base_url: http://127.0.0.1:11434/v1   # Ollama; LM Studio is http://127.0.0.1:1234/v1
    api_key_env: OPENAI_API_KEY           # read only when base_url is not localhost
```

Provider tier defaults (in code, overridable above):

| provider | fast | balanced | quality |
|---|---|---|---|
| claude | haiku | sonnet | opus |
| codex | gpt-5-mini | gpt-5 | gpt-5 with `model_reasoning_effort = "high"` |
| gemini | gemini-2.5-flash | gemini-2.5-pro | gemini-2.5-pro |
| openai_http | none — `probe()` lists the server's models; doctor fails until all three are set |

Existing per-role keys (`worker.router_model`, `extractor_model`, `digest_model`,
`profile_model`, `relevance_model`, chat's `DEFAULT_CHAT_MODEL`) keep their values;
they pass through `to_tier()`, so `haiku` still means "the fast tier of whatever
provider is active".

The desktop's `llmProvider` setting is re-typed to `claude | codex | gemini | local`
(`local` ↔ `openai_http`) and written through `PUT /v1/settings` into `llm.provider`;
the sidecar's config file is the single source of truth, the desktop mirrors it.

### 3. Batch adapters

- **`claude_cli.py`** — today's `client.py` subprocess code moved verbatim: `--json-schema`,
  `--model <alias>`, `--max-budget-usd`, images via the existing mechanism.
- **`codex_cli.py`** — `codex exec --json --sandbox read-only --skip-git-repo-check
  --ephemeral -m <model> -` with the prompt on stdin and the system prompt prepended as
  a fenced instruction block (Codex has no system-prompt flag). Structured output:
  `--output-schema <tmpfile>`; the final answer is the last `item.completed` event with
  `item.type == "agent_message"`, parsed as JSON when a schema was given. Reasoning effort
  for the quality tier via `-c model_reasoning_effort="high"`. Images: refused with
  `LLMError("codex: image input unsupported in non-interactive mode")`.
- **`gemini_cli.py`** — `gemini -p <prompt> --output-format json -m <model>`; the JSON
  `response` field is the text. Structured output: the schema is embedded in the prompt
  ("Respond with JSON matching this schema, nothing else"), parsed with the existing
  tolerant parser; on failure one retry with the stricter instruction, then `LLMError`.
  System prompt prepended like Codex. Images via `@path` attachments in the prompt.
- **`openai_http.py`** — `POST {base_url}/chat/completions` with `httpx`, `messages`
  built from system + user (+ image parts as base64 data URLs), `response_format:
  {"type": "json_schema", ...}` when a schema is given; for Ollama base URLs
  (`/api/tags` answers) the request additionally sets `format: <schema>` on `/api/chat`,
  which is the reliably enforced path. Non-localhost base URLs send
  `Authorization: Bearer $<api_key_env>`.

All adapters return `LLMResult` with `text`, `parsed` (when a schema was given),
`model`, and `cost_usd` (0 for non-Claude).

### 4. Chat drivers

Every driver yields the existing renderer events and nothing else.

- **Claude** — `run_chat_turn` moved verbatim.
- **Codex** — per turn: a run dir `~/ghostbrain/run/codex/` used as `CODEX_HOME`,
  containing a generated `config.toml` with `[mcp_servers.poltergeist]` (command = our
  binary + `mcp`, `required = true`) and one `[mcp_servers.<name>]` per opted-in user
  server (`command`, `args`, `env`), `sandbox_mode = "read-only"`, `approval_policy =
  "never"`, `model = <tier model>`; `auth.json` is symlinked from the user's real
  `CODEX_HOME` so the subscription login is reused without ever writing to it. Command:
  `codex exec --json --skip-git-repo-check -` (prompt on stdin) or `codex exec resume
  <session_id> --json -` for a continued conversation. Mapping: `thread.started` →
  `session`; `item.started` with `item.type == "mcp_tool_call"` → `tool` (name and
  summary from the item); `item.completed` with `agent_message` → `delta` (whole text,
  Codex does not stream tokens in exec mode) then `done`; `turn.failed` / `error` →
  `error`.
- **Gemini** — per turn: a temp workspace dir containing `.gemini/settings.json` with
  `mcpServers` (Poltergeist + opted-in servers, each with `trust: true` and
  `includeTools` limited to the granted tools) and `security.auth.selectedType` copied
  from the user's `~/.gemini/settings.json`; command `gemini -p <prompt>
  --output-format stream-json --approval-mode=yolo -m <model>` run with that cwd.
  Mapping: `init` → `session`; `message` (assistant) → `delta`; `tool_use` → `tool`;
  `result` → `done`; `error` → `error`. Resume: `--resume <session_id>` when the
  installed CLI advertises it in `--help`; otherwise the driver sends the stored
  conversation history as a prefixed transcript (the same fallback `repo/chat.py` uses
  after `ResumeFailed`).
- **Local (`openai_http`)** — a tool loop in-process: `POST /chat/completions` with
  `stream: true` and `tools` = the four vault tools (`poltergeist_search`,
  `poltergeist_get_note`, `poltergeist_ask`, `poltergeist_write_doc`) as function
  definitions generated from the MCP server's own tool schemas
  (`ghostbrain/mcp`); text chunks → `delta`; each `tool_calls` entry → `tool`, executed
  by calling the MCP tool implementation directly and appended as a `role: tool`
  message; at most 8 rounds per turn, then `done`. The `session` event carries the
  conversation id; history comes from the chat store via `ChatRequest.history`.
  Ollama base URLs use `/api/chat` (which documents streaming tool calls) instead of
  `/v1/chat/completions`.

`allowed_tools` semantics are unchanged: vault tools always; user servers only when
opted in (and never on local).

### 5. Doctor, API, desktop

- **Doctor** — the `claude-cli` check is replaced by `llm-provider` (all platforms,
  registered in its place): Claude → `claude` on PATH and `claude --version`; Codex →
  `codex` on PATH and `codex login status` exit 0; Gemini → `gemini` on PATH and an
  auth type in `~/.gemini/settings.json` (`oauth-personal`, `gemini-api-key`, or
  `vertex-ai`); local → `GET {base_url}/models` answers and the three tier models are
  configured and present in the list. Summary names the provider and model tiers; fix is
  `manual` with the install/login or Settings instruction. `checks.md` and
  `SKILL.md` are updated accordingly (the skill asks which provider the user has before
  step 3).
- **API** — `GET /v1/llm/providers` → `{active, providers: {id: ProviderProbe}}`
  (local includes `models`); `PUT /v1/settings` accepts `llm.provider`, `llm.models`,
  `llm.openai_http.base_url`. `/v1/answer` and `POST /v1/chat/*` return 412 with the
  probe reason when the active provider is not usable.
- **Desktop** — Settings → "AI provider": provider dropdown, a diagnostics row from the
  probe with a "re-check" button, and for local a base URL field plus three model
  pickers populated from `probe().detail.models`. The chat header carries a provider
  switcher: every provider is listed, those whose probe failed are disabled with the
  reason in the label, and choosing another one switches the active provider for the
  next turn. The `llmProvider` schema enum changes; onboarding is untouched.

## Error handling

- Provider not usable → `LLMError(probe.reason)` from `complete()`/`chat()`; the worker
  already audits `llm failed`; the API maps it to 412 on `/v1/answer` and chat start.
- CLI missing mid-run (uninstalled after the probe) → the same `LLMError` path.
- Structured output on Gemini/local: one retry, then `LLMError`; callers keep their
  existing "no result" handling.
- Codex image requests → `LLMError` before spawning; the only image call site
  (attachment captions) already treats a failed caption as "no caption".
- Timeouts: every driver honors `timeout_s` and kills its process group like Claude
  does today; the local driver uses `httpx` timeouts.
- Generated CLI config dirs are recreated per turn and never contain secrets beyond
  what the user's own CLI config already holds (auth is symlinked, not copied).

## Testing

- **Unit:** `to_tier()` synonyms and rejection; each provider's `models()` with and
  without overrides; `get_provider()` selection and the Claude default.
- **Contract (recorded fixtures):** `tests/fixtures/llm/codex-exec.jsonl`,
  `gemini-stream.jsonl`, `gemini-json.json` captured from real CLI runs; each CLI driver's
  parser is tested against them (event mapping, tool events, done text, error paths).
  Codex/Gemini command construction is tested by asserting the argv and the generated
  config files, with the subprocess stubbed.
- **Local driver:** a fake OpenAI-compatible server (stdlib `http.server`, like the
  fetch-model test) serving scripted streaming responses including a `tool_calls`
  round; asserts the event sequence and that the tool ran against the vault.
- **Regression:** the existing 24 call sites' tests run unchanged with the Claude
  adapter (bit-identical argv assertion for `claude -p`).
- **Doctor/API/desktop:** `llm-provider` check per provider with stubbed probes;
  `/v1/llm/providers` route test; settings screen vitest for the dropdown and the local
  model pickers.
- **Manual acceptance:** one real chat turn with a vault tool call and one batch
  extraction per provider on a machine where that CLI is logged in (Codex, Gemini) or
  Ollama is running, recorded in the PR.

## Slices (implementation order)

1. Protocol, `to_tier()`, Claude adapter extracted, `run()`/`run_chat_turn()` dispatch —
   behavior-identical refactor with the regression assertion.
2. Config block + tier defaults + `get_provider()`; desktop `llmProvider` re-typed and
   wired to `/v1/settings`.
3. `openai_http` batch adapter (+ Ollama `format`), then its chat tool loop.
4. Codex batch adapter, then its chat driver with the isolated `CODEX_HOME`.
5. Gemini batch adapter, then its chat driver with the workspace settings file.
6. Doctor `llm-provider` check, `GET /v1/llm/providers`, 412 gating, skill/docs updates.
7. Desktop AI-provider settings panel and chat header.
8. Manual acceptance per provider; release as 1.6.0.
