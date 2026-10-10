import { spawn, type ChildProcess } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { delimiter, join } from 'node:path';
import { app } from 'electron';

export interface SidecarInfo {
  port: number;
  token: string;
}

type Status = 'idle' | 'starting' | 'ready' | 'failed' | 'stopped';

interface FailureInfo {
  reason: string;
  stdoutTail: string;
  stderrTail: string;
}

interface SpawnTarget {
  exe: string;
  args: string[];
  cwd: string;
}

export interface SidecarOptions {
  schedulerEnabled?: boolean;
  vaultPath?: string;
}

export function buildSidecarEnv(
  base: NodeJS.ProcessEnv,
  opts: { schedulerEnabled: boolean; vaultPath: string; extraPath: string },
): NodeJS.ProcessEnv {
  const inheritedPath = base.PATH ?? '';
  const home = base.HOME ?? homedir();
  const vault = opts.vaultPath.startsWith('~/') ? join(home, opts.vaultPath.slice(2)) : opts.vaultPath;
  return {
    ...base,
    // Use the platform PATH delimiter (';' on Windows, ':' elsewhere), not a
    // hardcoded ':' — a hardcoded colon mangles a Windows PATH.
    PATH: inheritedPath ? `${opts.extraPath}${delimiter}${inheritedPath}` : opts.extraPath,
    PYTHONUNBUFFERED: '1',
    GHOSTBRAIN_SCHEDULER_ENABLED: opts.schedulerEnabled ? '1' : '0',
    VAULT_PATH: vault,
    // Have the sidecar shut itself down (stopping any live recording) when
    // its stdin hits EOF, i.e. when this process dies without calling stop().
    GHOSTBRAIN_PARENT_WATCH: '1',
  };
}

/**
 * Extra directories to prepend to PATH so the sidecar can shell out to
 * `claude`, `whisper-cli`, `gh`, `ffmpeg`, etc. even when the app was
 * launched with a stripped PATH (macOS launchd hands the .app just
 * `/usr/bin:/bin:/usr/sbin:/sbin`).
 *
 * `/opt/homebrew/bin` (Apple Silicon) and `/usr/local/bin` (Intel + manual
 * installs) are POSIX-only paths that don't exist on Windows, so they're
 * skipped there. `~/.local/bin` (Claude Code's default install path) is
 * kept on every platform.
 */
export function buildExtraPath(platform: NodeJS.Platform, home: string): string {
  const userLocalBin = home ? join(home, '.local', 'bin') : '';
  const posixExtras = platform === 'win32' ? [] : ['/opt/homebrew/bin', '/usr/local/bin'];
  return [...posixExtras, userLocalBin].filter(Boolean).join(delimiter);
}

const READY_LINE_RE = /^READY port=(\d+) token=([0-9a-f]+)/m;
const STARTUP_TIMEOUT_MS = 10_000;
const RESTART_BACKOFF_MS = 2_000;
const MAX_RESTART_ATTEMPTS = 1;

// stop() ladder: SIGTERM -> STOP_GRACE_MS -> SIGINT -> STOP_FORCE_MS -> SIGKILL
// -> STOP_KILL_WAIT_MS. SIGTERM runs uvicorn's graceful shutdown: usually ~3 s,
// worst case ~23 s (3 s graceful timeout + scheduler.stop()'s 10 s + whisper
// server's 5 s + 5 s), so the grace covers that with a little slack. A second
// signal (SIGINT) makes uvicorn force-exit, skipping the remaining hooks;
// SIGKILL is the last resort. before-quit awaits stop(), so the total (~30 s)
// is also the upper bound on how long a quit can hang before the app exits.
// On win32 kill() hard-terminates whatever signal is named, so the first step
// ends it.
export const STOP_GRACE_MS = 25_000;
export const STOP_FORCE_MS = 3_000;
const STOP_KILL_WAIT_MS = 2_000;

function hasExited(proc: ChildProcess): boolean {
  // Not `proc.killed`: that flips as soon as a signal is *sent*.
  return proc.exitCode !== null || proc.signalCode !== null;
}

/** Resolves true once `proc` has exited, or false after `ms` if it hasn't. */
function waitForExit(proc: ChildProcess, ms: number): Promise<boolean> {
  if (hasExited(proc)) return Promise.resolve(true);
  return new Promise((resolve) => {
    const onExit = () => {
      clearTimeout(timer);
      resolve(true);
    };
    const timer = setTimeout(() => {
      proc.off('exit', onExit);
      resolve(hasExited(proc));
    }, ms);
    proc.once('exit', onExit);
  });
}

function bundledSidecar(): SpawnTarget | null {
  // In packaged builds the PyInstaller --onedir bundle is shipped via
  // electron-builder `extraResources` at resources/sidecar/ghostbrain-api/.
  const isWin = process.platform === 'win32';
  const exeName = isWin ? 'ghostbrain-api.exe' : 'ghostbrain-api';
  const exe = join(process.resourcesPath, 'sidecar', 'ghostbrain-api', exeName);
  if (!existsSync(exe)) return null;
  // The bundle is self-contained; cwd just needs to be writable / sane.
  return { exe, args: [], cwd: app.getPath('userData') };
}

function devSidecar(repoRoot: string): SpawnTarget {
  // Dev fallback: spawn `python -m ghostbrain.api` from the project venv.
  const isWin = process.platform === 'win32';
  const venvPython = isWin
    ? join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : join(repoRoot, '.venv', 'bin', 'python');
  const exe = existsSync(venvPython) ? venvPython : isWin ? 'python' : 'python3';
  return { exe, args: ['-m', 'ghostbrain.api'], cwd: repoRoot };
}

/**
 * Path to the native macOS capture helper (ScreenCaptureKit), if present.
 * Packaged builds ship it via electron-builder `extraResources` at
 * resources/bin/ghostbrain-capture; dev builds use the SwiftPM release output
 * under native/. The sidecar reads GHOSTBRAIN_CAPTURE_BIN to find it, falling
 * back to its own discovery (PATH / ~/.local/bin) when unset.
 */
export function captureHelperPath(repoRoot: string): string | null {
  if (process.platform !== 'darwin') return null;
  const candidate = app.isPackaged
    ? join(process.resourcesPath, 'bin', 'ghostbrain-capture')
    : join(repoRoot, 'native', 'macos', 'ghostbrain-capture', '.build', 'release', 'ghostbrain-capture');
  return existsSync(candidate) ? candidate : null;
}

function resolveSpawnTarget(repoRoot: string): SpawnTarget {
  // Packaged builds must use the bundled binary — they don't have a venv to
  // fall back to. Dev builds use the venv. If a dev tester ever wants to
  // exercise the packaged sidecar locally, run `pnpm build` first.
  if (app.isPackaged) {
    const bundled = bundledSidecar();
    if (!bundled) {
      throw new Error(
        `Bundled sidecar not found at ${join(process.resourcesPath, 'sidecar', 'ghostbrain-api')}`,
      );
    }
    return bundled;
  }
  return devSidecar(repoRoot);
}

export class Sidecar extends EventEmitter {
  private proc: ChildProcess | null = null;
  private info: SidecarInfo | null = null;
  private status: Status = 'idle';
  private restartAttempts = 0;
  private stdoutBuf = '';
  private stderrBuf = '';
  // Flag the spawn-level exit handler reads to distinguish "we killed it" from
  // "it died on us". Without this, stop() trips the auto-restart logic, which
  // schedules a spawn() 2s later that collides with the fresh process started
  // by the next start() call.
  private intentionalStop = false;
  private restartTimer: NodeJS.Timeout | null = null;

  constructor(
    private readonly cwd: string,
    private readonly options: SidecarOptions = {},
  ) {
    super();
  }

  setSchedulerEnabled(enabled: boolean): void {
    this.options.schedulerEnabled = enabled;
  }

  setVaultPath(path: string): void {
    this.options.vaultPath = path;
  }

  getStatus(): Status {
    return this.status;
  }

  getInfo(): SidecarInfo | null {
    return this.info;
  }

  async start(): Promise<SidecarInfo> {
    if (this.status === 'ready' && this.info) return this.info;
    if (this.status === 'starting') {
      return new Promise((resolve, reject) => {
        this.once('ready', resolve);
        this.once('failed', (info: FailureInfo) => reject(new Error(info.reason)));
      });
    }
    this.status = 'starting';
    return this.spawn();
  }

  async stop(): Promise<void> {
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    if (!this.proc) {
      this.status = 'stopped';
      return;
    }
    const proc = this.proc;
    this.intentionalStop = true;
    // stdin is deliberately left open: its EOF means "parent died" to the
    // sidecar, which would also end a live recording that a normal quit keeps.
    if (!hasExited(proc)) {
      proc.kill('SIGTERM');
      if (!(await waitForExit(proc, STOP_GRACE_MS))) {
        proc.kill('SIGINT');
        if (!(await waitForExit(proc, STOP_FORCE_MS))) {
          proc.kill('SIGKILL');
          await waitForExit(proc, STOP_KILL_WAIT_MS);
        }
      }
    }
    this.proc = null;
    this.info = null;
    this.status = 'stopped';
  }

  private spawn(): Promise<SidecarInfo> {
    return new Promise((resolve, reject) => {
      let target: SpawnTarget;
      try {
        target = resolveSpawnTarget(this.cwd);
      } catch (err) {
        const reason = err instanceof Error ? err.message : String(err);
        this.fail(reason);
        reject(err instanceof Error ? err : new Error(reason));
        return;
      }
      const { exe, args, cwd } = target;
      // macOS launchd hands the .app a stripped PATH (`/usr/bin:/bin:/usr/sbin:/sbin`),
      // so the sidecar can't find `claude`, `whisper-cli`, `gh`, or `ffmpeg` —
      // all of which live in `/opt/homebrew/bin` (Apple Silicon), `/usr/local/bin`
      // (Intel + manual installs), or `~/.local/bin` (Claude Code's default
      // install path). Prepend those so the sidecar can shell out to them
      // regardless of how the app was launched (Dock, Finder, terminal).
      const extraPath = buildExtraPath(process.platform, process.env.HOME ?? '');
      const captureBin = captureHelperPath(this.cwd);
      const proc = spawn(exe, args, {
        cwd,
        // stdin stays an open pipe for the sidecar's lifetime (nothing is
        // written to it): the OS closes it only when this process dies, which
        // is what GHOSTBRAIN_PARENT_WATCH listens for.
        stdio: ['pipe', 'pipe', 'pipe'],
        env: {
          ...buildSidecarEnv(process.env, {
            schedulerEnabled: this.options.schedulerEnabled ?? false,
            vaultPath: this.options.vaultPath ?? '',
            extraPath,
          }),
          ...(captureBin ? { GHOSTBRAIN_CAPTURE_BIN: captureBin } : {}),
        },
      });
      this.proc = proc;
      this.stdoutBuf = '';
      this.stderrBuf = '';
      this.intentionalStop = false;
      if (this.restartTimer) {
        clearTimeout(this.restartTimer);
        this.restartTimer = null;
      }

      const timeout = setTimeout(() => {
        proc.kill();
        this.fail('Sidecar did not become ready within 10s');
        reject(new Error('Sidecar startup timeout'));
      }, STARTUP_TIMEOUT_MS);

      proc.stdout?.on('data', (chunk: Buffer) => {
        const text = chunk.toString();
        this.stdoutBuf = (this.stdoutBuf + text).slice(-4_000);
        const match = text.match(READY_LINE_RE);
        if (match && this.info === null) {
          clearTimeout(timeout);
          this.info = {
            port: parseInt(match[1]!, 10),
            token: match[2]!,
          };
          this.status = 'ready';
          this.restartAttempts = 0;
          this.emit('ready', this.info);
          resolve(this.info);
        }
      });

      proc.stderr?.on('data', (chunk: Buffer) => {
        this.stderrBuf = (this.stderrBuf + chunk.toString()).slice(-4_000);
      });

      proc.on('error', (err) => {
        clearTimeout(timeout);
        this.fail(`Could not spawn ${exe}: ${err.message}`);
        reject(err);
      });

      proc.on('exit', (code, signal) => {
        if (this.intentionalStop) {
          // stop() initiated this. Don't fail, don't auto-restart. The matching
          // once('exit') in stop() resolves the shutdown promise.
          clearTimeout(timeout);
          return;
        }
        if (this.status !== 'ready') {
          // Failed during startup
          clearTimeout(timeout);
          this.fail(
            `Sidecar exited during startup (code=${code} signal=${signal}). stderr: ${this.stderrBuf.slice(-500)}`,
          );
          return;
        }
        // Unexpected exit after ready
        this.info = null;
        this.status = 'failed';
        if (this.restartAttempts < MAX_RESTART_ATTEMPTS) {
          this.restartAttempts++;
          this.restartTimer = setTimeout(() => {
            this.restartTimer = null;
            this.spawn().catch(() => {
              // already emitted 'failed'
            });
          }, RESTART_BACKOFF_MS);
        } else {
          this.fail(
            `Sidecar crashed and auto-restart exhausted. last stderr: ${this.stderrBuf.slice(-500)}`,
          );
        }
      });
    });
  }

  private fail(reason: string): void {
    this.status = 'failed';
    const info: FailureInfo = {
      reason,
      stdoutTail: this.stdoutBuf.slice(-500),
      stderrTail: this.stderrBuf.slice(-500),
    };
    this.emit('failed', info);
  }
}
