import { spawn as nodeSpawn, type ChildProcess } from 'node:child_process';
import { existsSync, lstatSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, statSync } from 'node:fs';
import { get as httpGet } from 'node:http';
import { createServer } from 'node:net';
import { homedir } from 'node:os';
import { basename, isAbsolute, join, relative, resolve } from 'node:path';
import type { DevServerResult } from '../shared/design-types';
import { buildExtraPath } from './sidecar';

// Dev servers for live-design worktree sessions. A Poltergeist worktree's
// `.poltergeist/run.json` names a package.json script (written by the
// bootstrap agent run, protected afterwards); we run it with a fixed argv
// (`npm run <script> -- --port N`, shell: false) on a free port in its own
// process group, so stopping it also stops whatever the script spawned.
//
// One server per worktree, shared by every viewer (panel, pop-out, Artefacts
// preview); stopped IDLE_MS after the last viewer releases it and on quit.

export interface RunConfig {
  script: string;
  port_flag: '--port' | '-p' | null;
  url_path: string;
}

export type PackageManager = 'npm' | 'pnpm' | 'yarn';

const IDLE_MS = 60_000;
const READY_MS = 120_000;
const POLL_MS = 500;
const TAIL_LINES = 20;
const MAX_ERRORS = 50;
const MAX_RESTARTS = 1;

const SCRIPT_RE = /^[A-Za-z0-9][\w:.-]{0,99}$/;
const URL_PATH_RE = /^\/[^\s\\]{0,199}$/;
const STDOUT_URL_RE = /https?:\/\/(?:localhost|127\.0\.0\.1):(\d+)/;
const ERROR_LINE_RE = /error|failed to compile|\[vite\] internal server error|module not found/i;
// eslint-disable-next-line no-control-regex
const ANSI_RE = /\u001b\[[0-9;?]*[A-Za-z]/g;

const OFFLINE_ENV = {
  POLTERGEIST_OFFLINE: '1',
  VITE_POLTERGEIST_OFFLINE: '1',
  NEXT_PUBLIC_POLTERGEIST_OFFLINE: '1',
  REACT_APP_POLTERGEIST_OFFLINE: '1',
};

function readJson(path: string): unknown {
  try {
    return JSON.parse(readFileSync(path, 'utf-8'));
  } catch {
    return null;
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** `appDir/.poltergeist/run.json`, validated; null when missing or invalid.
 *  The script must be one of `appDir/package.json`'s scripts. */
export function readRunConfig(appDir: string): RunConfig | null {
  const raw = readJson(join(appDir, '.poltergeist', 'run.json'));
  if (!isRecord(raw)) return null;
  const { script } = raw;
  const portFlag = raw.port_flag ?? null;
  const urlPath = raw.url_path ?? '/';
  if (typeof script !== 'string' || !SCRIPT_RE.test(script)) return null;
  if (portFlag !== null && portFlag !== '--port' && portFlag !== '-p') return null;
  if (typeof urlPath !== 'string' || !URL_PATH_RE.test(urlPath)) return null;
  const pkg = readJson(join(appDir, 'package.json'));
  if (!isRecord(pkg) || !isRecord(pkg.scripts) || typeof pkg.scripts[script] !== 'string') return null;
  return { script, port_flag: portFlag, url_path: urlPath };
}

export function devServerArgv(pm: PackageManager, cfg: RunConfig, port: number): string[] {
  const portArgs = cfg.port_flag ? [cfg.port_flag, String(port)] : [];
  if (pm === 'yarn') return ['yarn', cfg.script, ...portArgs];
  return [pm, 'run', cfg.script, ...(portArgs.length ? ['--', ...portArgs] : [])];
}

export function packageManager(appDir: string): PackageManager {
  if (existsSync(join(appDir, 'pnpm-lock.yaml'))) return 'pnpm';
  if (existsSync(join(appDir, 'yarn.lock'))) return 'yarn';
  return 'npm';
}

function isInside(parent: string, child: string): boolean {
  const rel = relative(resolve(parent), resolve(child));
  return rel === '' || (!rel.startsWith('..') && !isAbsolute(rel));
}

/** A worktree Poltergeist created: `<repo>-poltergeist-<date>-<slug>` whose
 *  `.git` is a file (linked worktree), never a main checkout. */
export function isPoltergeistWorktree(worktree: string): boolean {
  if (!isAbsolute(worktree) || !basename(worktree).includes('-poltergeist-')) return false;
  try {
    return lstatSync(join(worktree, '.git')).isFile();
  } catch {
    return false;
  }
}

/** Callers pass realpaths. */
export function isAllowedWorktree(worktree: string, appDir: string): boolean {
  if (!isPoltergeistWorktree(worktree) || !isAbsolute(appDir) || !isInside(worktree, appDir)) return false;
  try {
    return statSync(join(appDir, '.poltergeist', 'run.json')).isFile();
  } catch {
    return false;
  }
}

/** HTTP status of a GET, rejecting on connection errors. node:http rather than
 *  fetch: undici's headers timeout can't be shortened per request. */
function defaultFetchStatus(url: string): Promise<number> {
  return new Promise((res, rej) => {
    const req = httpGet(url, (resp) => {
      resp.resume();
      res(resp.statusCode ?? 0);
    });
    req.setTimeout(2_000, () => req.destroy(new Error('timeout')));
    req.on('error', rej);
  });
}

function defaultFreePort(): Promise<number> {
  return new Promise((res, rej) => {
    const srv = createServer();
    srv.unref();
    srv.on('error', rej);
    srv.listen(0, '127.0.0.1', () => {
      const addr = srv.address();
      const port = typeof addr === 'object' && addr ? addr.port : 0;
      srv.close(() => (port ? res(port) : rej(new Error('no free port'))));
    });
  });
}

/** Kill the child's whole process group (it was spawned detached), so the
 *  script's own children (vite, next, …) go too. */
function defaultKillGroup(child: ChildProcess, signal: NodeJS.Signals): void {
  const pid = child.pid;
  if (!pid) return;
  if (process.platform === 'win32') {
    try {
      nodeSpawn('taskkill', ['/pid', String(pid), '/T', '/F'], { shell: false, stdio: 'ignore' }).on(
        'error',
        () => child.kill(),
      );
    } catch {
      child.kill();
    }
    return;
  }
  try {
    process.kill(-pid, signal);
  } catch {
    try {
      child.kill(signal);
    } catch {
      // already gone
    }
  }
}

// The dev server runs code the agent edited — not only app sources but
// anything its config imports, node_modules included — so on macOS it runs
// under sandbox-exec: no outbound network except loopback, no writes outside
// the worktree, temp and package caches, and no reads of credentials or the
// vault. Name-based file protection in the sidecar is only a first line.
export const SANDBOX_EXEC = '/usr/bin/sandbox-exec';

// Only the server's own port on loopback; no DNS (mDNSResponder would carry
// lookups like <secret>.example.com out), no pasteboard, no unix sockets
// (docker, ssh-agent), no LaunchServices / Apple Events / open (those start
// processes outside the sandbox). Writes go only to build caches — never to
// sources, package.json or dotfiles that something unsandboxed (an install,
// the user's editor, direnv) would later run. Vite's bundled-config temp
// file next to its config is the one exception.
export const SANDBOX_PROFILE = `(version 1)
(allow default)
(deny network*)
(allow network-bind (local ip "localhost:*"))
(allow network-inbound (local ip "localhost:*"))
(allow network-outbound (remote ip (string-append "localhost:" (param "PORT"))))
(deny mach-lookup
  (global-name "com.apple.dnssd.service")
  (global-name "com.apple.mDNSResponder")
  (global-name "com.apple.mDNSResponderHelper")
  (global-name "com.apple.pasteboard.1")
  (global-name "com.apple.coreservices.launchservicesd")
  (global-name "com.apple.coreservices.quarantine-resolver"))
(deny process-exec
  (literal "/usr/bin/open")
  (literal "/usr/bin/osascript")
  (literal "/usr/bin/pbcopy")
  (literal "/usr/bin/sandbox-exec"))
(deny lsopen)
(deny appleevent-send)
(deny file-write*)
(allow file-write*
  (subpath (param "SCRATCH"))
  (subpath (param "APP_NM_CACHE"))
  (subpath (param "APP_NM_VITE"))
  (subpath (param "APP_NEXT"))
  (subpath (param "APP_SVELTE"))
  (subpath (param "APP_NUXT"))
  (subpath (param "APP_ANGULAR"))
  (regex (string-append "^" (param "APP_RE") "/[^/]+\\\\.timestamp-[^/]+\\\\.mjs$"))
  (literal "/dev/null")
  (literal "/dev/tty")
  (regex #"^/dev/fd/"))
(deny file-read*
  (subpath (param "HOME_SSH"))
  (subpath (param "HOME_AWS"))
  (subpath (param "HOME_GNUPG"))
  (subpath (param "KEYCHAINS"))
  (subpath (param "APP_SUPPORT"))
  (subpath (param "CLAUDE"))
  (subpath (param "GH"))
  (subpath (param "GB_STATE"))
  (subpath (param "VAULT")))
`;

export interface SandboxPaths {
  worktree: string;
  appDir: string;
  home: string;
  port: number;
  vault: string | null;
}

function regexEscape(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** argv wrapped in sandbox-exec with the profile's parameters. */
export function sandboxArgv(argv: string[], p: SandboxPaths): string[] {
  const params: Record<string, string> = {
    PORT: String(p.port),
    SCRATCH: sandboxScratch(p.worktree).base,
    APP_NM_CACHE: join(p.appDir, 'node_modules', '.cache'),
    APP_NM_VITE: join(p.appDir, 'node_modules', '.vite'),
    APP_NEXT: join(p.appDir, '.next'),
    APP_SVELTE: join(p.appDir, '.svelte-kit'),
    APP_NUXT: join(p.appDir, '.nuxt'),
    APP_ANGULAR: join(p.appDir, '.angular'),
    APP_RE: regexEscape(p.appDir),
    HOME_SSH: join(p.home, '.ssh'),
    HOME_AWS: join(p.home, '.aws'),
    HOME_GNUPG: join(p.home, '.gnupg'),
    KEYCHAINS: join(p.home, 'Library', 'Keychains'),
    APP_SUPPORT: join(p.home, 'Library', 'Application Support'),
    CLAUDE: join(p.home, '.claude'),
    GH: join(p.home, '.config', 'gh'),
    GB_STATE: join(p.home, '.ghostbrain'),
    // No vault configured: deny a path that can't exist rather than nothing.
    VAULT: p.vault ?? join(p.worktree, '.no-vault'),
  };
  const defs = Object.entries(params).flatMap(([k, v]) => ['-D', `${k}=${v}`]);
  return [SANDBOX_EXEC, '-p', SANDBOX_PROFILE, ...defs, ...argv];
}

/** Scratch dirs inside the worktree for temp files and the npm cache. */
export function sandboxScratch(worktree: string): {
  base: string;
  tmp: string;
  npmCache: string;
  npmLogs: string;
} {
  const base = join(worktree, 'node_modules', '.cache', 'poltergeist');
  return { base, tmp: join(base, 'tmp'), npmCache: join(base, 'npm'), npmLogs: join(base, 'npm-logs') };
}

/** Folders the sandboxed server may write. They hold compiled code that a
 *  later, unsandboxed run (the user starting the worktree themselves) would
 *  execute, so they are wiped whenever a sandboxed server starts or exits. */
export function sandboxWritableCaches(worktree: string, appDir: string): string[] {
  return [
    sandboxScratch(worktree).base,
    join(appDir, 'node_modules', '.cache'),
    join(appDir, 'node_modules', '.vite'),
    join(appDir, '.next'),
    join(appDir, '.svelte-kit'),
    join(appDir, '.nuxt'),
    join(appDir, '.angular'),
  ];
}

export function wipeSandboxCaches(worktree: string, appDir: string): void {
  for (const dir of sandboxWritableCaches(worktree, appDir)) {
    // Rename first, then delete the renamed entry: whatever is there at the
    // moment of the rename (folder or planted symlink) is what gets removed,
    // and rm never follows a symlink.
    const doomed = `${dir}.gb-wipe-${process.pid}-${Date.now()}`;
    try {
      renameSync(dir, doomed);
    } catch {
      continue; // absent
    }
    try {
      rmSync(doomed, { recursive: true, force: true });
    } catch {
      // best effort; the next start wipes again
    }
  }
  try {
    for (const name of readdirSync(appDir)) {
      if (/\.timestamp-[^/]+\.mjs$/.test(name)) rmSync(join(appDir, name), { force: true });
    }
  } catch {
    // app dir gone
  }
}

/** Thrown by the wrapper when no sandbox is available: never run unsandboxed. */
export class SandboxUnavailableError extends Error {}

export interface DevServersOptions {
  spawn?: typeof nodeSpawn;
  /** Wraps the dev-server argv (sandbox); default: sandbox-exec on macOS,
   *  and a SandboxUnavailableError elsewhere. */
  wrap?: (argv: string[], worktree: string, port: number, appDir: string) => string[];
  /** Wipe the writable caches on start/exit (default true; off in unit tests). */
  wipeCaches?: boolean;
  /** Resolves with the HTTP status of a GET to `url`; rejects when unreachable. */
  fetch?: (url: string) => Promise<number>;
  freePort?: () => Promise<number>;
  killGroup?: (child: ChildProcess, signal: NodeJS.Signals) => void;
  idleMs?: number;
  readyMs?: number;
}

interface Server {
  worktree: string;
  appDir: string;
  cfg: RunConfig | null;
  port: number;
  child: ChildProcess | null;
  url: string | null;
  viewers: Set<string>;
  errors: string[];
  tail: string[];
  restarts: number;
  /** Set when the server died for good; the next ensure reports it. */
  failed: string | null;
  stopped: boolean;
  idleTimer: ReturnType<typeof setTimeout> | null;
  ready: Promise<DevServerResult>;
  settle: ((r: DevServerResult) => void) | null;
  cancelStart: (() => void) | null;
}

// The dev server runs agent-edited code (and whatever its config loads), so
// it gets a minimal environment: never the app's own env with API keys,
// tokens or the sidecar's settings.
const ENV_ALLOW = ['HOME', 'USER', 'LOGNAME', 'SHELL', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR', 'TERM', 'TZ', 'NVM_DIR', 'VOLTA_HOME'];

export function devServerBaseEnv(source: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { NODE_ENV: 'development' };
  for (const key of ENV_ALLOW) {
    if (source[key] !== undefined) env[key] = source[key];
  }
  return env;
}

/** CSP added to every response from a worktree dev server shown in a frame.
 *  The app runs agent-edited code with meeting content in reach: it may talk
 *  to its own dev server (HTTP + HMR websocket) and load Google Fonts, but
 *  nothing else — the offline mocks replace the real backend. */
export function devServerCsp(origin: string): string {
  const ws = origin.replace(/^http:/, 'ws:');
  return [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    `connect-src 'self' ${ws}`,
    "worker-src 'self' blob:",
    "form-action 'self'",
    "frame-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
  ].join('; ');
}

let vaultForSandbox: string | null = null;

/** The vault folder the sandbox must hide from dev servers. */
export function setSandboxVault(dir: string | null): void {
  vaultForSandbox = dir;
}

function defaultWrap(argv: string[], worktree: string, port: number, appDir: string): string[] {
  if (process.platform !== 'darwin' || !existsSync(SANDBOX_EXEC)) {
    throw new SandboxUnavailableError(
      'Existing-codebase previews need the macOS sandbox; not available on this system',
    );
  }
  return sandboxArgv(argv, { worktree, appDir, home: homedir(), port, vault: vaultForSandbox });
}

export class DevServers {
  private readonly servers = new Map<string, Server>();
  private readonly spawn: typeof nodeSpawn;
  private readonly fetchStatus: (url: string) => Promise<number>;
  private readonly freePort: () => Promise<number>;
  private readonly killGroup: (child: ChildProcess, signal: NodeJS.Signals) => void;
  private readonly idleMs: number;
  private readonly readyMs: number;
  private readonly wrap: (argv: string[], worktree: string, port: number, appDir: string) => string[];
  private readonly wipe: boolean;

  constructor(opts: DevServersOptions = {}) {
    this.spawn = opts.spawn ?? nodeSpawn;
    this.fetchStatus = opts.fetch ?? defaultFetchStatus;
    this.freePort = opts.freePort ?? defaultFreePort;
    this.killGroup = opts.killGroup ?? defaultKillGroup;
    this.idleMs = opts.idleMs ?? IDLE_MS;
    this.readyMs = opts.readyMs ?? READY_MS;
    this.wrap = opts.wrap ?? defaultWrap;
    this.wipe = opts.wipeCaches ?? true;
  }

  /** Start (or reuse) the worktree's dev server and add `viewer` to it.
   *  Returns the URL plus compile errors seen since the previous call. */
  async ensure(worktree: string, appDir: string, viewer = 'default'): Promise<DevServerResult> {
    let s = this.servers.get(worktree);
    if (s?.failed) {
      this.drop(s);
      return { ok: false, error: s.failed };
    }
    if (!s) {
      const cfg = readRunConfig(appDir);
      if (!cfg) return { ok: false, error: 'No valid .poltergeist/run.json in the app folder' };
      s = this.create(worktree, appDir, cfg);
      void this.boot(s);
    }
    s.viewers.add(viewer);
    if (s.idleTimer) {
      clearTimeout(s.idleTimer);
      s.idleTimer = null;
    }
    const r = await s.ready;
    if (!r.ok) return r;
    if (s.failed) return { ok: false, error: s.failed };
    const errors = s.errors;
    s.errors = [];
    return { ok: true, url: s.url ?? r.url, errors };
  }

  release(worktree: string, viewer = 'default'): void {
    const s = this.servers.get(worktree);
    if (!s) return;
    s.viewers.delete(viewer);
    if (s.viewers.size === 0 && !existsSync(worktree)) {
      // The worktree was removed: nothing left to serve.
      this.stop(s, 'SIGKILL');
      return;
    }
    if (s.viewers.size === 0 && !s.idleTimer) {
      s.idleTimer = setTimeout(() => this.stop(s), this.idleMs);
    }
  }

  /** A window went away: drop it from every server it was viewing. */
  releaseViewer(viewer: string): void {
    for (const s of [...this.servers.values()]) {
      if (s.viewers.has(viewer)) this.release(s.worktree, viewer);
    }
  }

  /** True when `origin` (`http://127.0.0.1:<port>`) is a running server's. */
  isKnownOrigin(origin: string): boolean {
    for (const s of this.servers.values()) {
      if (s.stopped || !s.port) continue;
      if (origin === `http://127.0.0.1:${s.port}` || origin === `http://localhost:${s.port}`) return true;
      if (s.url && new URL(s.url).origin === origin) return true;
    }
    return false;
  }

  stopAll(): void {
    for (const s of [...this.servers.values()]) this.stop(s, 'SIGKILL');
  }

  private create(worktree: string, appDir: string, cfg: RunConfig): Server {
    const s: Server = {
      worktree,
      appDir,
      cfg,
      port: 0,
      child: null,
      url: null,
      viewers: new Set(),
      errors: [],
      tail: [],
      restarts: 0,
      failed: null,
      stopped: false,
      idleTimer: null,
      ready: Promise.resolve({ ok: false, error: '' }),
      settle: null,
      cancelStart: null,
    };
    this.resetReady(s);
    this.servers.set(worktree, s);
    return s;
  }

  private resetReady(s: Server): void {
    s.ready = new Promise<DevServerResult>((res) => {
      s.settle = (r) => {
        s.settle = null;
        s.cancelStart?.();
        s.cancelStart = null;
        res(r);
      };
    });
  }

  private async boot(s: Server): Promise<void> {
    try {
      s.port = await this.freePort();
    } catch (e) {
      this.fail(s, `Could not find a free port: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    if (s.stopped) return;
    this.launch(s);
  }

  private launch(s: Server): void {
    const cfg = s.cfg as RunConfig;
    let wrapped: string[];
    try {
      wrapped = this.wrap(devServerArgv(packageManager(s.appDir), cfg, s.port), s.worktree, s.port, s.appDir);
    } catch (e) {
      this.fail(s, e instanceof Error ? e.message : String(e));
      return;
    }
    const [cmd = 'npm', ...args] = wrapped;
    if (this.wipe) wipeSandboxCaches(s.worktree, s.appDir);
    const scratch = sandboxScratch(s.worktree);
    for (const dir of [scratch.tmp, scratch.npmCache, scratch.npmLogs]) {
      try {
        mkdirSync(dir, { recursive: true });
      } catch {
        // the server reports it if it really needs the folder
      }
    }
    const extraPath = buildExtraPath(process.platform, process.env.HOME ?? '');
    const inherited = process.env.PATH ?? '';
    const env: NodeJS.ProcessEnv = {
      ...devServerBaseEnv(process.env),
      PATH: inherited ? `${extraPath}${process.platform === 'win32' ? ';' : ':'}${inherited}` : extraPath,
      PORT: String(s.port),
      BROWSER: 'none',
      TMPDIR: scratch.tmp,
      npm_config_cache: scratch.npmCache,
      npm_config_logs_dir: scratch.npmLogs,
      npm_config_update_notifier: 'false',
      ...OFFLINE_ENV,
    };
    let child: ChildProcess;
    try {
      child = this.spawn(cmd, args, {
        cwd: s.appDir,
        env,
        shell: false,
        detached: process.platform !== 'win32',
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      });
    } catch (e) {
      this.fail(s, `Could not start the dev server: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    s.child = child;
    if (this.wipe) child.once('exit', () => wipeSandboxCaches(s.worktree, s.appDir));
    s.url = null;

    const onLine = (line: string) => {
      if (s.child !== child) return;
      const clean = line.replace(ANSI_RE, '').trimEnd();
      if (!clean.trim()) return;
      s.tail.push(clean);
      if (s.tail.length > TAIL_LINES) s.tail.shift();
      if (ERROR_LINE_RE.test(clean) && s.errors.length < MAX_ERRORS) s.errors.push(clean.trim());
      const m = s.settle ? STDOUT_URL_RE.exec(clean) : null;
      if (m) {
        s.url = `http://localhost:${m[1]}${cfg.url_path}`;
        s.settle?.({ ok: true, url: s.url, errors: [] });
      }
    };
    for (const stream of [child.stdout, child.stderr]) {
      let buf = '';
      stream?.setEncoding?.('utf-8');
      stream?.on('data', (chunk: string | Buffer) => {
        buf += chunk.toString();
        const lines = buf.split(/\r?\n/);
        buf = lines.pop() ?? '';
        lines.forEach(onLine);
      });
    }
    child.on('error', (err) => {
      if (s.child !== child) return;
      this.kill(s, 'SIGKILL');
      this.fail(s, `Could not start the dev server: ${err.message}`);
    });
    child.on('exit', () => this.onExit(s, child));

    this.watchReady(s, cfg);
  }

  private watchReady(s: Server, cfg: RunConfig): void {
    let poll: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;
    const deadline = setTimeout(() => {
      const tail = s.tail.join('\n');
      this.kill(s, 'SIGKILL');
      this.fail(s, `Dev server did not start within ${Math.round(this.readyMs / 1000)}s: ${tail}`);
    }, this.readyMs);
    s.cancelStart = () => {
      cancelled = true;
      clearTimeout(deadline);
      if (poll) clearTimeout(poll);
    };
    const url = `http://127.0.0.1:${s.port}${cfg.url_path}`;
    const tick = () => {
      poll = null;
      this.fetchStatus(url).then(
        (status) => {
          if (cancelled) return;
          if (status > 0 && status < 500) {
            s.url = url;
            s.settle?.({ ok: true, url, errors: [] });
          } else {
            poll = setTimeout(tick, POLL_MS);
          }
        },
        () => {
          if (!cancelled) poll = setTimeout(tick, POLL_MS);
        },
      );
    };
    poll = setTimeout(tick, POLL_MS);
  }

  private onExit(s: Server, child: ChildProcess): void {
    if (s.child !== child || s.stopped) return;
    s.child = null;
    const msg = `Dev server exited: ${s.tail.join('\n')}`;
    if (s.settle) {
      // Died while starting: nothing to restart into.
      this.fail(s, msg);
      return;
    }
    if (s.viewers.size === 0) {
      this.drop(s);
      return;
    }
    if (s.restarts >= MAX_RESTARTS) {
      s.failed = msg;
      return;
    }
    s.restarts += 1;
    if (s.errors.length < MAX_ERRORS) s.errors.push(msg);
    s.tail = [];
    this.resetReady(s);
    this.launch(s);
  }

  /** Settle a pending start with an error and forget the server. */
  private fail(s: Server, error: string): void {
    this.drop(s);
    if (s.settle) s.settle({ ok: false, error });
    else s.failed = error;
  }

  private kill(s: Server, signal: NodeJS.Signals): void {
    const child = s.child;
    s.child = null;
    if (child) this.killGroup(child, signal);
  }

  private stop(s: Server, _signal: NodeJS.Signals = 'SIGKILL'): void {
    if (s.stopped) return;
    s.stopped = true;
    this.drop(s);
    // Always the whole group at once: a grandchild left running (vite under
    // npm) could write the caches again after they are wiped.
    this.kill(s, 'SIGKILL');
    s.settle?.({ ok: false, error: 'Dev server stopped' });
    if (this.wipe) {
      wipeSandboxCaches(s.worktree, s.appDir);
      // And once more after the group is surely gone.
      const t = setTimeout(() => wipeSandboxCaches(s.worktree, s.appDir), 1_000);
      t.unref?.();
    }
  }

  private drop(s: Server): void {
    if (s.idleTimer) {
      clearTimeout(s.idleTimer);
      s.idleTimer = null;
    }
    if (this.servers.get(s.worktree) === s) this.servers.delete(s.worktree);
  }
}
