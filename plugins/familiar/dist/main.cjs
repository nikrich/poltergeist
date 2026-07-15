var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/main.js
var main_exports = {};
__export(main_exports, {
  activate: () => activate,
  deactivate: () => deactivate
});
module.exports = __toCommonJS(main_exports);
var import_node_fs = require("node:fs");
var import_node_path = require("node:path");

// src/lib/schedule.js
var DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
function lastScheduledSlot(config2, now) {
  const target = DAYS.indexOf(config2.day);
  const d = new Date(now);
  d.setHours(config2.hour, 0, 0, 0);
  d.setDate(d.getDate() - (d.getDay() - target + 7) % 7);
  if (d > now) d.setDate(d.getDate() - 7);
  return d;
}
function isRunDue(config2, state, now = /* @__PURE__ */ new Date()) {
  const s = state ?? {};
  if (!s.lastSuccessfulRunAt) return true;
  return new Date(s.lastSuccessfulRunAt) < lastScheduledSlot(config2, now);
}
function inFailureCooldown(state, now, cooldownMs = 4 * 36e5) {
  const s = state ?? {};
  if (!s.lastAttemptAt) return false;
  const lastAttempt = new Date(s.lastAttemptAt).getTime();
  const lastSuccess = s.lastSuccessfulRunAt ? new Date(s.lastSuccessfulRunAt).getTime() : 0;
  const attemptFailed = lastAttempt > lastSuccess;
  const withinCooldown = now.getTime() - lastAttempt < cooldownMs;
  return attemptFailed && withinCooldown;
}
function nextRunAt(config2, now = /* @__PURE__ */ new Date()) {
  const next = new Date(lastScheduledSlot(config2, now));
  next.setDate(next.getDate() + 7);
  return next;
}

// src/lib/delta.js
function localYmd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function listDays(sinceIso, nowIso) {
  const d = new Date(sinceIso);
  d.setHours(0, 0, 0, 0);
  const end = new Date(nowIso);
  end.setHours(0, 0, 0, 0);
  const out = [];
  while (d <= end) {
    out.push(localYmd(d));
    d.setDate(d.getDate() + 1);
  }
  return out;
}
function extractPaths(rows) {
  const seen = /* @__PURE__ */ new Set();
  for (const row of rows) {
    const p = row?.path;
    if (typeof p === "string" && p && !p.startsWith("Familiar/")) seen.add(p);
  }
  return [...seen];
}

// src/lib/budget.js
function trimToBudget(notes, maxChars) {
  const kept = [...notes].sort((a, b) => String(a.modified).localeCompare(String(b.modified)));
  const dropped = [];
  const total = () => kept.reduce((n, x) => n + x.text.length, 0);
  while (kept.length > 1 && total() > maxChars) dropped.push(kept.shift().path);
  return { kept, dropped };
}
function renderNoteBlocks(notes) {
  return notes.map((n) => `<note path="${n.path}" modified="${n.modified ?? ""}">
${n.text}
</note>`).join("\n\n");
}

// src/lib/prompt.js
var SYSTEM_PROMPT = [
  "You are Familiar, a personal chief of staff reviewing your principal's",
  "second-brain vault. You are skeptical and concrete. You never invent",
  "commitments, decisions, or facts: every open loop and decision must be",
  "traceable to a source note, cited by its vault-relative path. You care",
  "about: commitments made and not yet delivered (open loops), decisions",
  "taken, recurring themes, contradictions between stated intent and",
  "observed activity, and blind spots (questions the principal should be",
  "asking). Prose is tight; bullets over paragraphs."
].join(" ");
function buildUserPrompt(p) {
  return [
    `# Review window: ${p.windowStart} \u2192 ${p.windowEnd}`,
    "",
    "## Your rolling memory (from last run; rewrite it in your output)",
    p.memoryMd || "(first run \u2014 no memory yet)",
    "",
    "## Current open-loops tracker",
    p.openLoopsMd || "(empty)",
    "",
    "Dismissed loops are read-only context: never modify, resurrect, or",
    "return them. Return the COMPLETE updated list of every non-dismissed",
    'loop: pass through loops still open, flip status to "done" when the',
    'new notes show completion, "stale" after ~3 weeks without movement,',
    "and append new loops with new ids (slug format: loop-<kebab-case>).",
    "",
    "## Current decisions tracker",
    p.decisionsMd || "(empty)",
    "",
    "## New and changed notes this window",
    p.noteBlocks || "(no changes this window)",
    "",
    ...p.droppedPaths.length ? [
      "## Notes omitted for length (coverage is PARTIAL; say so in the briefing)",
      ...p.droppedPaths.map((x) => `- ${x}`),
      ""
    ] : [],
    "## Output",
    "Return ONLY a JSON object matching the provided schema:",
    "{briefingMarkdown, memoryMarkdown, openLoops, decisions}.",
    "briefingMarkdown: the briefing \u2014 sections: Themes, Open loops",
    "(summary of notable ones), Decisions, Contradictions, Blind spots.",
    "memoryMarkdown: your rewritten rolling memory \u2014 active themes,",
    "watch-list, condensed history. decisions: ONLY decisions newly seen",
    "this window."
  ].join("\n");
}

// src/lib/output.js
var SWEEP_JSON_SCHEMA = {
  type: "object",
  required: ["briefingMarkdown", "memoryMarkdown", "openLoops", "decisions"],
  properties: {
    briefingMarkdown: { type: "string" },
    memoryMarkdown: { type: "string" },
    openLoops: {
      type: "array",
      items: {
        type: "object",
        required: ["id", "text", "sourcePath", "firstSeen", "status"],
        properties: {
          id: { type: "string", pattern: "^loop-[a-z0-9-]+$" },
          text: { type: "string" },
          owedTo: { type: ["string", "null"] },
          sourcePath: { type: "string" },
          firstSeen: { type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$" },
          status: { type: "string", enum: ["open", "done", "stale"] }
        }
      }
    },
    decisions: {
      type: "array",
      items: {
        type: "object",
        required: ["date", "text", "sourcePath"],
        properties: {
          date: { type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$" },
          text: { type: "string" },
          sourcePath: { type: "string" }
        }
      }
    }
  }
};
var LOOP_ID_RE = /^loop-[a-z0-9-]+$/;
var STATUSES = /* @__PURE__ */ new Set(["open", "done", "stale"]);
function extractJson(text) {
  const fenced = /```(?:json)?\s*\n([\s\S]*?)\n?```/.exec(text);
  const raw = fenced ? fenced[1] : text;
  try {
    return JSON.parse(raw);
  } catch (e) {
    throw new Error(`output is not valid JSON: ${e.message}`);
  }
}
function parseSweepOutput(res) {
  const data = res.structured ?? extractJson(res.text ?? "");
  for (const k of ["briefingMarkdown", "memoryMarkdown", "openLoops", "decisions"]) {
    if (!(k in (data ?? {}))) throw new Error(`output missing key: ${k}`);
  }
  if (typeof data.briefingMarkdown !== "string" || typeof data.memoryMarkdown !== "string") {
    throw new Error("briefingMarkdown/memoryMarkdown must be strings");
  }
  if (!data.briefingMarkdown.trim()) {
    throw new Error("briefingMarkdown must not be empty or whitespace-only");
  }
  if (!data.memoryMarkdown.trim()) {
    throw new Error("memoryMarkdown must not be empty or whitespace-only");
  }
  if (!Array.isArray(data.openLoops)) {
    throw new Error("openLoops must be an array");
  }
  if (!Array.isArray(data.decisions)) {
    throw new Error("decisions must be an array");
  }
  for (const l of data.openLoops) {
    if (!LOOP_ID_RE.test(l.id ?? "")) throw new Error(`bad loop id: ${JSON.stringify(l.id)}`);
    if (!STATUSES.has(l.status)) throw new Error(`bad loop status: ${JSON.stringify(l.status)}`);
    if (typeof l.text !== "string" || typeof l.sourcePath !== "string") {
      throw new Error(`loop ${l.id}: text/sourcePath must be strings`);
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(l.firstSeen ?? "")) {
      throw new Error(`loop ${l.id}: firstSeen must match YYYY-MM-DD format`);
    }
    if (typeof l.owedTo !== "string" && l.owedTo !== null && l.owedTo !== void 0) {
      throw new Error(`loop ${l.id}: owedTo must be a string or null`);
    }
    l.owedTo ??= null;
  }
  for (const d of data.decisions) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d.date ?? "")) throw new Error(`bad decision date: ${JSON.stringify(d.date)}`);
    if (typeof d.text !== "string") {
      throw new Error("decision text must be a string");
    }
    if (typeof d.sourcePath !== "string") {
      throw new Error("decision sourcePath must be a string");
    }
  }
  return data;
}

// src/lib/trackers.js
var OWED_SEP = " \u2014 owed to ";
var LOOP_RE = new RegExp(
  "^- \\[( |x)\\] <!--id:([a-z0-9-]+)--> (.+) \\(from \\[source\\]\\((.+)\\), first seen (\\d{4}-\\d{2}-\\d{2})\\)(?: \\{(stale|dismissed)\\})?$"
);
function parseOpenLoops(md) {
  const loops = [];
  const unparsed = [];
  for (const line of md.split("\n")) {
    if (!line.startsWith("- ")) continue;
    const m = LOOP_RE.exec(line);
    if (!m) {
      unparsed.push(line);
      continue;
    }
    const [, box, id, head, sourcePath, firstSeen, tag] = m;
    const sepIdx = head.lastIndexOf(OWED_SEP);
    const text = sepIdx === -1 ? head : head.slice(0, sepIdx);
    const owedTo = sepIdx === -1 ? null : head.slice(sepIdx + OWED_SEP.length);
    loops.push({
      id,
      text,
      owedTo,
      sourcePath,
      firstSeen,
      status: box === "x" ? "done" : tag ?? "open"
    });
  }
  return { loops, unparsed };
}
function sanitizeField(s) {
  if (s == null) return s;
  return s.replace(/ — owed to /g, " - owed to ").replace(/\(from \[source\]\(/g, "(from [source] (").replace(/\s*\n\s*/g, " ");
}
function renderLoop(l) {
  const box = l.status === "done" ? "x" : " ";
  const text = sanitizeField(l.text);
  const owedTo = l.owedTo ? sanitizeField(l.owedTo) : null;
  const owed = owedTo ? `${OWED_SEP}${owedTo}` : "";
  const tag = l.status === "stale" || l.status === "dismissed" ? ` {${l.status}}` : "";
  return `- [${box}] <!--id:${l.id}--> ${text}${owed} (from [source](${l.sourcePath}), first seen ${l.firstSeen})${tag}`;
}
function renderOpenLoops(loops, unparsed) {
  const lines = ["# Open loops", "", ...loops.map(renderLoop)];
  if (unparsed.length) lines.push("", "## Unparsed", "", ...unparsed);
  return lines.join("\n") + "\n";
}
function mergeLoops(current, fromModel) {
  const byId = new Map(current.map((l) => [l.id, l]));
  const out = [];
  for (const cur of current) {
    const m = fromModel.find((x) => x.id === cur.id);
    if (!m || cur.status === "done" || cur.status === "dismissed") {
      out.push(cur);
      continue;
    }
    const status = m.status === "dismissed" ? cur.status : m.status;
    out.push({ ...cur, status });
  }
  for (const m of fromModel) {
    if (byId.has(m.id)) continue;
    out.push({ ...m, owedTo: m.owedTo ?? null, status: m.status === "dismissed" ? "open" : m.status });
  }
  return out;
}
var DECISION_RE = /^- (\d{4}-\d{2}-\d{2}) — (.+) \(from \[source\]\((.+)\)\)$/;
function parseDecisions(md) {
  const out = [];
  for (const line of md.split("\n")) {
    const m = DECISION_RE.exec(line);
    if (m) out.push({ date: m[1], text: m[2], sourcePath: m[3] });
  }
  return out;
}
function renderDecisions(list) {
  return ["# Decisions", "", ...list.map((d) => `- ${d.date} \u2014 ${sanitizeField(d.text)} (from [source](${d.sourcePath}))`)].join("\n") + "\n";
}
function mergeDecisions(current, fromModel) {
  const key = (d) => `${d.date}${sanitizeField(d.text)}`;
  const seen = new Set(current.map(key));
  const out = [...current];
  for (const d of fromModel) {
    if (!seen.has(key(d))) {
      seen.add(key(d));
      out.push(d);
    }
  }
  return out;
}

// src/lib/sweep.js
var MEMORY_PATH = "Familiar/memory.md";
var LOOPS_PATH = "Familiar/open-loops.md";
var DECISIONS_PATH = "Familiar/decisions.md";
var briefingPath = (ymd) => `Familiar/briefings/${ymd}.md`;
function localYmd2(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
async function getJson(api, path) {
  const r = await api.fetch("GET", path);
  if (!r.ok) throw new Error(`GET ${path}: ${r.error}`);
  return r.data;
}
async function readNoteData(api, notePath) {
  const r = await api.fetch("GET", `/v1/notes?path=${encodeURIComponent(notePath)}`);
  if (r.ok) return r.data;
  if (r.status === 404) return null;
  throw new Error(`read ${notePath}: ${r.error}`);
}
async function readNote(api, notePath) {
  const data = await readNoteData(api, notePath);
  return data ? data.body : null;
}
async function writeNote(api, notePath, content) {
  const r = await api.fetch("PUT", "/v1/notes", { path: notePath, content });
  if (!r.ok) throw new Error(`write ${notePath}: ${r.error}`);
}
async function runSweep(deps) {
  const { api, settings, state, now, log } = deps;
  const windowStart = state.lastSuccessfulRunAt ?? new Date(now.getTime() - 7 * 24 * 3600 * 1e3).toISOString();
  const windowEnd = now.toISOString();
  const report = {
    ok: false,
    windowStart,
    windowEnd,
    noteCount: 0,
    droppedCount: 0,
    costUsd: null
  };
  try {
    const pathSet = [];
    for (const day of listDays(windowStart, windowEnd)) {
      const rows = await getJson(api, `/v1/activity?date=${day}&windowMinutes=1440`);
      pathSet.push(...rows);
    }
    const paths = extractPaths(pathSet);
    const notes = [];
    for (const p of paths) {
      const data = await readNoteData(api, p);
      if (data !== null) {
        const modified = data.frontmatter?.updated ?? data.frontmatter?.created ?? "";
        notes.push({ path: p, modified, text: data.body });
      }
    }
    const { kept, dropped } = trimToBudget(notes, settings.budgetChars);
    report.noteCount = kept.length;
    report.droppedCount = dropped.length;
    const memoryMd = await readNote(api, MEMORY_PATH) ?? "";
    const loopsMd = await readNote(api, LOOPS_PATH) ?? "";
    const decisionsMd = await readNote(api, DECISIONS_PATH) ?? "";
    const userPrompt = buildUserPrompt({
      memoryMd,
      openLoopsMd: loopsMd,
      decisionsMd,
      noteBlocks: renderNoteBlocks(kept),
      droppedPaths: dropped,
      windowStart,
      windowEnd
    });
    let output = null;
    let lastErr = null;
    let lastRawText = "";
    for (let attempt = 0; attempt < 2 && !output; attempt++) {
      const prompt = lastErr ? `${userPrompt}

Your previous output was rejected: ${lastErr}. Return ONLY the JSON object.` : userPrompt;
      const r = await api.fetch("POST", "/v1/llm/run", {
        prompt,
        system: SYSTEM_PROMPT,
        model: settings.model,
        jsonSchema: SWEEP_JSON_SCHEMA,
        timeoutSeconds: 840,
        // The backend's claude client defaults to a $0.50/call safety cap;
        // an opus sweep at the full budgetChars deterministically exceeds
        // that, so raise the cap for this call specifically.
        budgetUsd: 5
      });
      if (!r.ok) throw new Error(`llm/run transport: ${r.error}`);
      if (r.data.error) throw new Error(`llm/run: ${r.data.error}`);
      report.costUsd = (report.costUsd ?? 0) + (r.data.costUsd ?? 0);
      lastRawText = r.data.text ?? "";
      try {
        output = parseSweepOutput(r.data);
      } catch (e) {
        lastErr = e.message;
        log(`sweep output rejected (attempt ${attempt + 1}): ${e.message}`);
      }
    }
    if (!output) {
      report.rawOutput = lastRawText;
      throw new Error(`output contract violated twice: ${lastErr}`);
    }
    const freshLoops = parseOpenLoops(await readNote(api, LOOPS_PATH) ?? "");
    const mergedLoops = mergeLoops(freshLoops.loops, output.openLoops);
    const freshDecisions = parseDecisions(await readNote(api, DECISIONS_PATH) ?? "");
    const mergedDecisions = mergeDecisions(freshDecisions, output.decisions);
    const ymd = localYmd2(now);
    const briefing = [
      "---",
      "type: familiar-briefing",
      `window: ${windowStart}..${windowEnd}`,
      `notes: ${kept.length}`,
      `dropped: ${dropped.length}`,
      `created: ${windowEnd}`,
      "---",
      "",
      output.briefingMarkdown
    ].join("\n");
    await writeNote(api, briefingPath(ymd), briefing);
    await writeNote(api, MEMORY_PATH, output.memoryMarkdown);
    await writeNote(api, LOOPS_PATH, renderOpenLoops(mergedLoops, freshLoops.unparsed));
    await writeNote(api, DECISIONS_PATH, renderDecisions(mergedDecisions));
    report.ok = true;
    report.briefingPath = briefingPath(ymd);
    return report;
  } catch (e) {
    report.error = e instanceof Error ? e.message : String(e);
    return report;
  }
}

// src/main.js
var TICK_MS = 15 * 60 * 1e3;
var FIRST_TICK_MS = 30 * 1e3;
var STALE_RUN_MS = 30 * 60 * 1e3;
var DEFAULT_CONFIG = { cadence: "weekly", day: "monday", hour: 7, model: "sonnet", budgetChars: 15e4 };
var VALID_DAYS = /* @__PURE__ */ new Set(["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]);
var VALID_MODELS = /* @__PURE__ */ new Set(["haiku", "sonnet", "opus"]);
function validateConfigPartial(partial) {
  if ("day" in partial && !VALID_DAYS.has(partial.day)) {
    throw new Error(`config.day must be one of ${[...VALID_DAYS].join(", ")}; got ${JSON.stringify(partial.day)}`);
  }
  if ("hour" in partial && (!Number.isInteger(partial.hour) || partial.hour < 0 || partial.hour > 23)) {
    throw new Error(`config.hour must be an integer 0-23; got ${JSON.stringify(partial.hour)}`);
  }
  if ("model" in partial && !VALID_MODELS.has(partial.model)) {
    throw new Error(`config.model must be one of ${[...VALID_MODELS].join(", ")}; got ${JSON.stringify(partial.model)}`);
  }
  if ("budgetChars" in partial && (!Number.isInteger(partial.budgetChars) || partial.budgetChars <= 0)) {
    throw new Error(`config.budgetChars must be a positive integer; got ${JSON.stringify(partial.budgetChars)}`);
  }
}
var ctx = null;
var timer = null;
var firstTimer = null;
var running = false;
var statePath = () => (0, import_node_path.join)(ctx.dataDir, "state.json");
var runsPath = () => (0, import_node_path.join)(ctx.dataDir, "runs.jsonl");
function loadState() {
  try {
    return JSON.parse((0, import_node_fs.readFileSync)(statePath(), "utf-8"));
  } catch {
    return {};
  }
}
function saveState(state) {
  (0, import_node_fs.mkdirSync)(ctx.dataDir, { recursive: true });
  (0, import_node_fs.writeFileSync)(statePath(), JSON.stringify(state, null, 2));
}
function config() {
  return { ...DEFAULT_CONFIG, ...ctx.settings.get("config") ?? {} };
}
function lastRuns(n = 10) {
  try {
    return (0, import_node_fs.readFileSync)(runsPath(), "utf-8").trim().split("\n").slice(-n).map((l) => JSON.parse(l));
  } catch {
    return [];
  }
}
async function sweep(trigger) {
  const c = ctx;
  const state = loadState();
  if (running) return { started: false, reason: "already running" };
  if (state.runningSince && Date.now() - new Date(state.runningSince).getTime() < STALE_RUN_MS) {
    return { started: false, reason: "run in progress" };
  }
  running = true;
  saveState({ ...state, runningSince: (/* @__PURE__ */ new Date()).toISOString(), lastAttemptAt: (/* @__PURE__ */ new Date()).toISOString() });
  const cfg = config();
  const startedAt = (/* @__PURE__ */ new Date()).toISOString();
  let report;
  try {
    report = await runSweep({
      api: c.api,
      settings: { model: cfg.model, budgetChars: cfg.budgetChars },
      state,
      now: /* @__PURE__ */ new Date(),
      log: c.log
    });
  } catch (e) {
    report = { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
  running = false;
  if (ctx === null) {
    return { started: true };
  }
  const next = loadState();
  delete next.runningSince;
  if (report.ok) next.lastSuccessfulRunAt = report.windowEnd;
  saveState(next);
  (0, import_node_fs.mkdirSync)(c.dataDir, { recursive: true });
  if (report.rawOutput) {
    (0, import_node_fs.writeFileSync)((0, import_node_path.join)(c.dataDir, `failed-${Date.now()}.txt`), report.rawOutput);
    delete report.rawOutput;
  }
  (0, import_node_fs.appendFileSync)(runsPath(), JSON.stringify({ startedAt, finishedAt: (/* @__PURE__ */ new Date()).toISOString(), trigger, ...report }) + "\n");
  c.ipc.send("run:finished", report);
  c.log(`sweep ${report.ok ? "ok" : `FAILED: ${report.error}`}`);
  return { started: true };
}
function tick() {
  const state = loadState();
  if (inFailureCooldown(state, /* @__PURE__ */ new Date())) return;
  if (isRunDue(config(), state, /* @__PURE__ */ new Date())) void sweep("schedule");
}
function activate(context) {
  ctx = context;
  ctx.ipc.handle("status", () => ({
    running,
    nextRunAt: nextRunAt(config(), /* @__PURE__ */ new Date()).toISOString(),
    lastSuccessfulRunAt: loadState().lastSuccessfulRunAt ?? null,
    config: config(),
    lastRuns: lastRuns()
  }));
  ctx.ipc.handle("run", () => sweep("manual"));
  ctx.ipc.handle("config:set", (partial) => {
    if (typeof partial !== "object" || partial === null) throw new Error("config must be an object");
    validateConfigPartial(partial);
    ctx.settings.set("config", { ...config(), ...partial });
    return config();
  });
  timer = setInterval(tick, TICK_MS);
  firstTimer = setTimeout(tick, FIRST_TICK_MS);
}
function deactivate() {
  if (timer) clearInterval(timer);
  if (firstTimer) clearTimeout(firstTimer);
  timer = firstTimer = null;
  ctx = null;
}
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  activate,
  deactivate
});
