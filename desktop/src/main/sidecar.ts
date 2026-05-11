import { spawn, type ChildProcess } from 'node:child_process';
import { EventEmitter } from 'node:events';

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

const READY_LINE_RE = /^READY port=(\d+) token=([0-9a-f]+)/m;
const STARTUP_TIMEOUT_MS = 10_000;
const RESTART_BACKOFF_MS = 2_000;
const MAX_RESTART_ATTEMPTS = 1;

function pythonExecutable(): string {
  // On Windows some installs only have `python` on PATH; check at runtime.
  // For dev we assume macOS / Linux with python3.
  return process.platform === 'win32' ? 'python' : 'python3';
}

export class Sidecar extends EventEmitter {
  private proc: ChildProcess | null = null;
  private info: SidecarInfo | null = null;
  private status: Status = 'idle';
  private restartAttempts = 0;
  private stdoutBuf = '';
  private stderrBuf = '';

  constructor(private readonly cwd: string) {
    super();
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
    if (!this.proc) {
      this.status = 'stopped';
      return;
    }
    const proc = this.proc;
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
      const exe = pythonExecutable();
      const proc = spawn(exe, ['-m', 'ghostbrain.api'], {
        cwd: this.cwd,
        env: { ...process.env, PYTHONUNBUFFERED: '1' },
      });
      this.proc = proc;
      this.stdoutBuf = '';
      this.stderrBuf = '';

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
          setTimeout(() => {
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
