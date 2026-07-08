import { readFileSync, writeFileSync, appendFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { isRunDue, nextRunAt } from './lib/schedule.js';
import { runSweep } from './lib/sweep.js';

const TICK_MS = 15 * 60 * 1000;
const FIRST_TICK_MS = 30 * 1000;
const STALE_RUN_MS = 30 * 60 * 1000;
const DEFAULT_CONFIG = { cadence: 'weekly', day: 'monday', hour: 7, model: 'sonnet', budgetChars: 150000 };

let ctx = null;
let timer = null;
let firstTimer = null;
let running = false;

const statePath = () => join(ctx.dataDir, 'state.json');
const runsPath = () => join(ctx.dataDir, 'runs.jsonl');

function loadState() {
  try {
    return JSON.parse(readFileSync(statePath(), 'utf-8'));
  } catch {
    return {};
  }
}

function saveState(state) {
  mkdirSync(ctx.dataDir, { recursive: true });
  writeFileSync(statePath(), JSON.stringify(state, null, 2));
}

function config() {
  return { ...DEFAULT_CONFIG, ...(ctx.settings.get('config') ?? {}) };
}

function lastRuns(n = 10) {
  try {
    return readFileSync(runsPath(), 'utf-8').trim().split('\n').slice(-n).map((l) => JSON.parse(l));
  } catch {
    return [];
  }
}

async function sweep(trigger) {
  const state = loadState();
  if (running) return { started: false, reason: 'already running' };
  if (state.runningSince && Date.now() - new Date(state.runningSince).getTime() < STALE_RUN_MS) {
    return { started: false, reason: 'run in progress' };
  }
  running = true;
  saveState({ ...state, runningSince: new Date().toISOString(), lastAttemptAt: new Date().toISOString() });
  const cfg = config();
  const startedAt = new Date().toISOString();
  let report;
  try {
    report = await runSweep({
      api: ctx.api,
      settings: { model: cfg.model, budgetChars: cfg.budgetChars },
      state,
      now: new Date(),
      log: ctx.log,
    });
  } catch (e) {
    report = { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
  running = false;
  const next = loadState();
  delete next.runningSince;
  if (report.ok) next.lastSuccessfulRunAt = report.windowEnd;
  saveState(next);
  mkdirSync(ctx.dataDir, { recursive: true });
  if (report.rawOutput) {
    // rejected LLM output, kept for debugging (spec §2.1); too big for runs.jsonl
    writeFileSync(join(ctx.dataDir, `failed-${Date.now()}.txt`), report.rawOutput);
    delete report.rawOutput;
  }
  appendFileSync(runsPath(), JSON.stringify({ startedAt, finishedAt: new Date().toISOString(), trigger, ...report }) + '\n');
  ctx.ipc.send('run:finished', report);
  ctx.log(`sweep ${report.ok ? 'ok' : `FAILED: ${report.error}`}`);
  return { started: true };
}

function tick() {
  if (isRunDue(config(), loadState(), new Date())) void sweep('schedule');
}

export function activate(context) {
  ctx = context;
  ctx.ipc.handle('status', () => ({
    running,
    nextRunAt: nextRunAt(config(), new Date()).toISOString(),
    lastSuccessfulRunAt: loadState().lastSuccessfulRunAt ?? null,
    config: config(),
    lastRuns: lastRuns(),
  }));
  ctx.ipc.handle('run', () => sweep('manual'));
  ctx.ipc.handle('config:set', (partial) => {
    if (typeof partial !== 'object' || partial === null) throw new Error('config must be an object');
    ctx.settings.set('config', { ...config(), ...partial });
    return config();
  });
  timer = setInterval(tick, TICK_MS);
  firstTimer = setTimeout(tick, FIRST_TICK_MS); // catch-up shortly after launch
}

export function deactivate() {
  // A sweep may be in flight here; that's acceptable — its runningSince
  // entry in state.json goes stale and is reaped after STALE_RUN_MS.
  if (timer) clearInterval(timer);
  if (firstTimer) clearTimeout(firstTimer);
  timer = firstTimer = null;
  ctx = null;
}
