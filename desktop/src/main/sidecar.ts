import { spawn, type ChildProcess } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
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

const READY_LINE_RE = /^READY port=(\d+) token=([0-9a-f]+)/m;
const STARTUP_TIMEOUT_MS = 10_000;
const RESTART_BACKOFF_MS = 2_000;
const MAX_RESTART_ATTEMPTS = 1;

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
    private readonly options: { schedulerEnabled?: boolean } = {},
  ) {
    super();
  }

  setSchedulerEnabled(enabled: boolean): void {
    this.options.schedulerEnabled = enabled;
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
    proc.kill('SIGTERM');
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        if (proc && !proc.killed) proc.kill('SIGKILL');
        resolve();
      }, 5_000);
      proc.once('exit', () => {
        clearTimeout(timer);
        resolve();
      });
    });
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
      const home = process.env.HOME ?? '';
      const userLocalBin = home ? `${home}/.local/bin` : '';
      const extraPath = ['/opt/homebrew/bin', '/usr/local/bin', userLocalBin]
        .filter(Boolean)
        .join(':');
      const inheritedPath = process.env.PATH ?? '';
      const proc = spawn(exe, args, {
        cwd,
        env: {
          ...process.env,
          PATH: inheritedPath ? `${extraPath}:${inheritedPath}` : extraPath,
          PYTHONUNBUFFERED: '1',
          GHOSTBRAIN_SCHEDULER_ENABLED: this.options.schedulerEnabled ? '1' : '0',
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
