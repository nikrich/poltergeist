import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({ app: { isPackaged: false, getPath: () => '/tmp' } }));

class FakeProc extends EventEmitter {
  stdout = new EventEmitter();
  stderr = new EventEmitter();
  exitCode: number | null = null;
  signalCode: NodeJS.Signals | null = null;
  // Mirrors Node: `killed` flips as soon as a signal is *sent*, not when the child exits.
  killed = false;
  signals: string[] = [];
  kill = vi.fn((signal: NodeJS.Signals = 'SIGTERM') => {
    this.signals.push(signal);
    this.killed = true;
    return true;
  });

  die(signal: NodeJS.Signals): void {
    this.signalCode = signal;
    this.emit('exit', null, signal);
  }
}

const spawned: { exe: string; args: string[]; opts: Record<string, unknown>; proc: FakeProc }[] = [];

vi.mock('node:child_process', () => {
  const spawn = vi.fn((exe: string, args: string[], opts: Record<string, unknown>) => {
    const proc = new FakeProc();
    spawned.push({ exe, args, opts, proc });
    return proc;
  });
  return { spawn, default: { spawn } };
});

import { buildSidecarEnv, Sidecar, STOP_FORCE_MS, STOP_GRACE_MS } from '../sidecar';

async function startReady(): Promise<{ sidecar: Sidecar; proc: FakeProc; opts: Record<string, unknown> }> {
  const sidecar = new Sidecar('/repo');
  const started = sidecar.start();
  const { proc, opts } = spawned[spawned.length - 1]!;
  proc.stdout.emit('data', Buffer.from('READY port=1234 token=abc123\n'));
  await started;
  return { sidecar, proc, opts };
}

beforeEach(() => {
  spawned.length = 0;
});

afterEach(() => {
  vi.useRealTimers();
});

describe('sidecar spawn', () => {
  it('tells the sidecar to watch its parent', () => {
    const env = buildSidecarEnv({ HOME: '/home/x' }, { schedulerEnabled: false, vaultPath: '/v', extraPath: '' });
    expect(env.GHOSTBRAIN_PARENT_WATCH).toBe('1');
  });

  it('spawns with the parent-watch env and stdin kept as an open pipe', async () => {
    const { opts, proc } = await startReady();
    expect((opts.env as NodeJS.ProcessEnv).GHOSTBRAIN_PARENT_WATCH).toBe('1');
    // stdin must stay a pipe: its EOF is the sidecar's "parent died" signal.
    expect(opts.stdio).toEqual(['pipe', 'pipe', 'pipe']);
    proc.die('SIGTERM');
  });
});

describe('Sidecar.stop', () => {
  it('sends SIGTERM and resolves when the sidecar exits, without escalating', async () => {
    vi.useFakeTimers();
    const { sidecar, proc } = await startReady();
    const stopped = sidecar.stop();
    expect(proc.signals).toEqual(['SIGTERM']);
    proc.die('SIGTERM');
    await stopped;
    await vi.advanceTimersByTimeAsync(STOP_GRACE_MS + STOP_FORCE_MS + 10_000);
    expect(proc.signals).toEqual(['SIGTERM']);
    expect(sidecar.getStatus()).toBe('stopped');
  });

  it('does not close stdin on a deliberate stop', async () => {
    vi.useFakeTimers();
    const stdin = { end: vi.fn(), destroy: vi.fn() };
    const { sidecar, proc } = await startReady();
    Object.assign(proc, { stdin });
    const stopped = sidecar.stop();
    proc.die('SIGTERM');
    await stopped;
    expect(stdin.end).not.toHaveBeenCalled();
    expect(stdin.destroy).not.toHaveBeenCalled();
  });

  it('resolves immediately when the sidecar had already exited', async () => {
    vi.useFakeTimers();
    const { sidecar, proc } = await startReady();
    proc.exitCode = 1;
    proc.emit('exit', 1, null);
    await sidecar.stop();
    expect(sidecar.getStatus()).toBe('stopped');
  });
});

// The SIGTERM -> SIGINT -> SIGKILL ladder is POSIX semantics; on win32 kill()
// hard-terminates whatever signal is named, so the first SIGTERM ends it.
describe.skipIf(process.platform === 'win32')('Sidecar.stop escalation', () => {
  it('escalates to SIGINT after the grace period even though proc.killed is already true', async () => {
    vi.useFakeTimers();
    const { sidecar, proc } = await startReady();
    const stopped = sidecar.stop();
    await vi.advanceTimersByTimeAsync(STOP_GRACE_MS - 1);
    expect(proc.signals).toEqual(['SIGTERM']);
    await vi.advanceTimersByTimeAsync(1);
    expect(proc.signals).toEqual(['SIGTERM', 'SIGINT']);
    proc.die('SIGINT');
    await stopped;
    await vi.advanceTimersByTimeAsync(STOP_FORCE_MS + 10_000);
    expect(proc.signals).toEqual(['SIGTERM', 'SIGINT']);
  });

  it('escalates to SIGKILL when SIGINT does not end it either', async () => {
    vi.useFakeTimers();
    const { sidecar, proc } = await startReady();
    let done = false;
    const stopped = sidecar.stop().then(() => {
      done = true;
    });
    await vi.advanceTimersByTimeAsync(STOP_GRACE_MS + STOP_FORCE_MS);
    expect(proc.signals).toEqual(['SIGTERM', 'SIGINT', 'SIGKILL']);
    expect(done).toBe(false);
    proc.die('SIGKILL');
    await stopped;
    expect(sidecar.getStatus()).toBe('stopped');
  });

  it('still resolves (bounded) if the process never reports exit', async () => {
    vi.useFakeTimers();
    const { sidecar, proc } = await startReady();
    let done = false;
    void sidecar.stop().then(() => {
      done = true;
    });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(proc.signals).toEqual(['SIGTERM', 'SIGINT', 'SIGKILL']);
    expect(done).toBe(true);
  });
});
