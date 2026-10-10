import { EventEmitter } from 'node:events';
import { existsSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { PassThrough } from 'node:stream';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

// Worktree dev servers are macOS-only (they run under sandbox-exec and fail
// closed elsewhere); these tests use POSIX paths, symlinks and process groups.
const describePosix = describe.skipIf(process.platform === 'win32');

vi.mock('electron', () => ({ app: { isPackaged: false, getPath: () => '/tmp' } }));

import {
  DevServers,
  devServerArgv,
  devServerBaseEnv,
  devServerCsp,
  sandboxArgv,
  SANDBOX_EXEC,
  SandboxUnavailableError,
  wipeSandboxCaches,
  isAllowedWorktree,
  packageManager,
  readRunConfig,
} from '../design-devserver';

class FakeChild extends EventEmitter {
  stdout = new PassThrough();
  stderr = new PassThrough();
  pid: number;
  kill = vi.fn();
  constructor(pid: number) {
    super();
    this.pid = pid;
  }
  print(line: string, stream: 'stdout' | 'stderr' = 'stdout') {
    this[stream].write(`${line}\n`);
  }
}

let root: string;

function makeWorktree(name: string, opts: { gitDir?: boolean; run?: object | null; scripts?: object } = {}) {
  const wt = join(root, name);
  mkdirSync(join(wt, '.poltergeist'), { recursive: true });
  if (opts.gitDir) mkdirSync(join(wt, '.git'));
  else writeFileSync(join(wt, '.git'), 'gitdir: /somewhere/.git/worktrees/x\n');
  writeFileSync(
    join(wt, 'package.json'),
    JSON.stringify({ name: 'app', scripts: opts.scripts ?? { dev: 'vite' } }),
  );
  if (opts.run !== null) {
    writeFileSync(
      join(wt, '.poltergeist', 'run.json'),
      JSON.stringify(opts.run ?? { script: 'dev', port_flag: '--port', url_path: '/' }),
    );
  }
  return wt;
}

beforeAll(() => {
  root = mkdtempSync(join(tmpdir(), 'gb-devserver-'));
});
afterAll(() => {
  rmSync(root, { recursive: true, force: true });
});

describePosix('readRunConfig', () => {
  it('reads a valid config', () => {
    const wt = makeWorktree('app-poltergeist-2026-10-10-ok');
    expect(readRunConfig(wt)).toEqual({ script: 'dev', port_flag: '--port', url_path: '/' });
  });

  it('defaults port_flag and url_path', () => {
    const wt = makeWorktree('app-poltergeist-2026-10-10-defaults', { run: { script: 'dev' } });
    expect(readRunConfig(wt)).toEqual({ script: 'dev', port_flag: null, url_path: '/' });
  });

  it('rejects a script not in package.json', () => {
    const wt = makeWorktree('app-poltergeist-2026-10-10-noscript', { run: { script: 'evil', port_flag: null } });
    expect(readRunConfig(wt)).toBeNull();
  });

  it('rejects an unknown port_flag', () => {
    const wt = makeWorktree('app-poltergeist-2026-10-10-flag', {
      run: { script: 'dev', port_flag: '--host=0.0.0.0' },
    });
    expect(readRunConfig(wt)).toBeNull();
  });

  it.each([
    [{ script: '--prefix=/tmp', port_flag: null }],
    [{ script: 'dev', url_path: 'http://evil.example/' }],
    [{ script: 'dev', url_path: '/a b' }],
    [{ script: 42 }],
    [[]],
  ])('rejects malformed config %j', (run) => {
    const wt = makeWorktree(`app-poltergeist-2026-10-10-bad-${Math.random().toString(36).slice(2)}`, {
      run: run as object,
      scripts: { dev: 'vite', '--prefix=/tmp': 'x' },
    });
    expect(readRunConfig(wt)).toBeNull();
  });

  it('returns null without run.json', () => {
    const wt = makeWorktree('app-poltergeist-2026-10-10-norun', { run: null });
    expect(readRunConfig(wt)).toBeNull();
  });
});

describePosix('devServerArgv / packageManager', () => {
  const cfg = { script: 'dev', port_flag: '--port' as const, url_path: '/' };
  it('npm and pnpm pass the port after --', () => {
    expect(devServerArgv('npm', cfg, 5555)).toEqual(['npm', 'run', 'dev', '--', '--port', '5555']);
    expect(devServerArgv('pnpm', { ...cfg, port_flag: '-p' }, 5555)).toEqual([
      'pnpm', 'run', 'dev', '--', '-p', '5555',
    ]);
    expect(devServerArgv('npm', { ...cfg, port_flag: null }, 5555)).toEqual(['npm', 'run', 'dev']);
  });

  it('yarn passes the flag directly', () => {
    expect(devServerArgv('yarn', cfg, 5555)).toEqual(['yarn', 'dev', '--port', '5555']);
    expect(devServerArgv('yarn', { ...cfg, port_flag: null }, 5555)).toEqual(['yarn', 'dev']);
  });

  it('detects the package manager from the lockfile', () => {
    const wt = makeWorktree('app-poltergeist-2026-10-10-pm');
    expect(packageManager(wt)).toBe('npm');
    writeFileSync(join(wt, 'yarn.lock'), '');
    expect(packageManager(wt)).toBe('yarn');
    writeFileSync(join(wt, 'pnpm-lock.yaml'), '');
    expect(packageManager(wt)).toBe('pnpm');
  });
});

describePosix('isAllowedWorktree', () => {
  it('accepts a Poltergeist worktree and a nested app dir', () => {
    const wt = makeWorktree('shop-poltergeist-2026-10-10-login');
    expect(isAllowedWorktree(wt, wt)).toBe(true);
    const nested = join(wt, 'apps', 'web');
    mkdirSync(join(nested, '.poltergeist'), { recursive: true });
    writeFileSync(join(nested, '.poltergeist', 'run.json'), '{"script":"dev"}');
    expect(isAllowedWorktree(wt, nested)).toBe(true);
  });

  it('rejects a normal repo (.git directory)', () => {
    const wt = makeWorktree('shop-poltergeist-2026-10-10-gitdir', { gitDir: true });
    expect(isAllowedWorktree(wt, wt)).toBe(false);
  });

  it('rejects a path without -poltergeist-', () => {
    const wt = makeWorktree('shop-feature-branch');
    expect(isAllowedWorktree(wt, wt)).toBe(false);
  });

  it('rejects an app dir outside the worktree', () => {
    const wt = makeWorktree('shop-poltergeist-2026-10-10-outside');
    const other = makeWorktree('other-poltergeist-2026-10-10-x');
    expect(isAllowedWorktree(wt, other)).toBe(false);
    expect(isAllowedWorktree(wt, join(wt, '..', 'other-poltergeist-2026-10-10-x'))).toBe(false);
  });

  it('rejects an app dir without run.json', () => {
    const wt = makeWorktree('shop-poltergeist-2026-10-10-norun', { run: null });
    expect(isAllowedWorktree(wt, wt)).toBe(false);
  });
});

describePosix('DevServers', () => {
  let wt: string;
  let children: FakeChild[];
  let spawn: ReturnType<typeof vi.fn>;
  let fetchStatus: ReturnType<typeof vi.fn>;
  let killGroup: ReturnType<typeof vi.fn>;
  let servers: DevServers;

  beforeEach(() => {
    vi.useFakeTimers();
    wt = makeWorktree(`shop-poltergeist-2026-10-10-${Math.random().toString(36).slice(2)}`);
    children = [];
    spawn = vi.fn(() => {
      const c = new FakeChild(1000 + children.length);
      children.push(c);
      return c;
    });
    fetchStatus = vi.fn(async () => {
      throw new Error('ECONNREFUSED');
    });
    killGroup = vi.fn();
    servers = new DevServers({
      spawn: spawn as never,
      fetch: fetchStatus as never,
      freePort: async () => 5555,
      killGroup: killGroup as never,
      wrap: (argv) => argv, // the sandbox wrapper has its own tests
      wipeCaches: false,
    });
  });

  afterEach(() => {
    servers.stopAll();
    vi.useRealTimers();
  });

  const child = (i: number): FakeChild => {
    const c = children[i];
    if (!c) throw new Error(`no child ${i}`);
    return c;
  };
  /** Let the server answer on the next poll. */
  const answer = (status = 200) => fetchStatus.mockImplementation(async () => status);

  it('starts with the expected argv/env/cwd and is ready on fetch 200', async () => {
    const p = servers.ensure(wt, wt, 'a');
    await vi.advanceTimersByTimeAsync(0);
    expect(spawn).toHaveBeenCalledTimes(1);
    const [cmd, args, opts] = spawn.mock.calls[0] ?? [];
    expect([cmd, ...args]).toEqual(['npm', 'run', 'dev', '--', '--port', '5555']);
    expect(opts.cwd).toBe(wt);
    expect(opts.shell).toBe(false);
    if (process.platform !== 'win32') expect(opts.detached).toBe(true);
    expect(opts.env).toMatchObject({
      PORT: '5555',
      BROWSER: 'none',
      POLTERGEIST_OFFLINE: '1',
      VITE_POLTERGEIST_OFFLINE: '1',
      NEXT_PUBLIC_POLTERGEIST_OFFLINE: '1',
      REACT_APP_POLTERGEIST_OFFLINE: '1',
    });
    if (process.platform !== 'win32') expect(opts.env.PATH).toContain('/opt/homebrew/bin');
    answer(200);
    await vi.advanceTimersByTimeAsync(500);
    await expect(p).resolves.toEqual({ ok: true, url: 'http://127.0.0.1:5555/', errors: [] });
    expect(fetchStatus).toHaveBeenCalledWith('http://127.0.0.1:5555/');
  });

  it('treats a 404 as ready but keeps polling on 5xx', async () => {
    fetchStatus.mockImplementation(async () => 502);
    let done = false;
    const p = servers.ensure(wt, wt, 'a').then((r) => {
      done = true;
      return r;
    });
    await vi.advanceTimersByTimeAsync(2000);
    expect(done).toBe(false);
    answer(404);
    await vi.advanceTimersByTimeAsync(500);
    await expect(p).resolves.toMatchObject({ ok: true });
  });

  it('reuses a running server and stops it 60 s after the last viewer leaves', async () => {
    answer();
    const a = servers.ensure(wt, wt, 'a');
    await vi.advanceTimersByTimeAsync(0);
    const b = servers.ensure(wt, wt, 'b');
    await vi.advanceTimersByTimeAsync(500);
    await expect(a).resolves.toMatchObject({ ok: true });
    await expect(b).resolves.toMatchObject({ ok: true });
    await expect(servers.ensure(wt, wt, 'a')).resolves.toMatchObject({ ok: true });
    expect(spawn).toHaveBeenCalledTimes(1);

    servers.release(wt, 'a');
    await vi.advanceTimersByTimeAsync(120_000);
    expect(killGroup).not.toHaveBeenCalled();

    servers.release(wt, 'b');
    await vi.advanceTimersByTimeAsync(59_000);
    expect(killGroup).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(killGroup).toHaveBeenCalledWith(child(0), expect.any(String));
  });

  it('a new viewer within the idle window cancels the stop', async () => {
    answer();
    const a = servers.ensure(wt, wt, 'a');
    await vi.advanceTimersByTimeAsync(500);
    await a;
    servers.release(wt, 'a');
    await vi.advanceTimersByTimeAsync(30_000);
    await servers.ensure(wt, wt, 'b');
    await vi.advanceTimersByTimeAsync(120_000);
    expect(killGroup).not.toHaveBeenCalled();
    expect(spawn).toHaveBeenCalledTimes(1);
  });

  it('releaseViewer drops a viewer from every server', async () => {
    answer();
    const a = servers.ensure(wt, wt, 'win-1');
    await vi.advanceTimersByTimeAsync(500);
    await a;
    servers.releaseViewer('win-1');
    await vi.advanceTimersByTimeAsync(60_000);
    expect(killGroup).toHaveBeenCalledTimes(1);
  });

  it('a stdout URL with a different port wins', async () => {
    const p = servers.ensure(wt, wt, 'a');
    await vi.advanceTimersByTimeAsync(0);
    child(0).print('  \u001b[32m➜\u001b[39m  Local:   http://localhost:5174/');
    await vi.advanceTimersByTimeAsync(0);
    await expect(p).resolves.toEqual({ ok: true, url: 'http://localhost:5174/', errors: [] });
  });

  it('never ready: errors after 120 s with the output tail and kills the child', async () => {
    const p = servers.ensure(wt, wt, 'a');
    await vi.advanceTimersByTimeAsync(0);
    child(0).print('compiling…');
    await vi.advanceTimersByTimeAsync(119_000);
    expect(killGroup).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1_500);
    const r = await p;
    expect(r.ok).toBe(false);
    expect(r.ok === false && r.error).toMatch(/^Dev server did not start within 120s: /);
    expect(r.ok === false && r.error).toContain('compiling…');
    expect(killGroup).toHaveBeenCalledWith(child(0), expect.any(String));
    // Gone: the next ensure starts fresh.
    void servers.ensure(wt, wt, 'a');
    await vi.advanceTimersByTimeAsync(0);
    expect(spawn).toHaveBeenCalledTimes(2);
  });

  it('error lines surface once', async () => {
    answer();
    const p = servers.ensure(wt, wt, 'a');
    await vi.advanceTimersByTimeAsync(500);
    await p;
    child(0).print('[vite] Internal server error: Failed to resolve import "./Nope"', 'stderr');
    child(0).print('page reload src/App.tsx');
    await vi.advanceTimersByTimeAsync(0);
    const r1 = await servers.ensure(wt, wt, 'a');
    expect(r1).toMatchObject({ ok: true });
    expect(r1.ok && r1.errors).toEqual(['[vite] Internal server error: Failed to resolve import "./Nope"']);
    const r2 = await servers.ensure(wt, wt, 'a');
    expect(r2.ok && r2.errors).toEqual([]);
  });

  it('restarts once when the server exits while viewed, then reports the exit', async () => {
    answer();
    const p = servers.ensure(wt, wt, 'a');
    await vi.advanceTimersByTimeAsync(500);
    await p;
    child(0).print('boom');
    await vi.advanceTimersByTimeAsync(0);
    child(0).emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(500);
    expect(spawn).toHaveBeenCalledTimes(2);
    const r = await servers.ensure(wt, wt, 'a');
    expect(r).toMatchObject({ ok: true });
    expect(r.ok && r.errors.join('\n')).toContain('Dev server exited');

    child(1).print('boom again');
    await vi.advanceTimersByTimeAsync(0);
    child(1).emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(500);
    expect(spawn).toHaveBeenCalledTimes(2);
    const r2 = await servers.ensure(wt, wt, 'a');
    expect(r2.ok).toBe(false);
    expect(r2.ok === false && r2.error).toMatch(/^Dev server exited: .*boom again/s);
  });

  it('an exit before ready fails the pending ensure', async () => {
    const p = servers.ensure(wt, wt, 'a');
    await vi.advanceTimersByTimeAsync(0);
    child(0).print('Error: Cannot find module vite', 'stderr');
    await vi.advanceTimersByTimeAsync(0);
    child(0).emit('exit', 1, null);
    const r = await p;
    expect(r.ok).toBe(false);
    expect(r.ok === false && r.error).toMatch(/^Dev server exited: .*Cannot find module vite/s);
  });

  it('a spawn error fails the pending ensure', async () => {
    const p = servers.ensure(wt, wt, 'a');
    await vi.advanceTimersByTimeAsync(0);
    child(0).emit('error', new Error('spawn npm ENOENT'));
    const r = await p;
    expect(r.ok === false && r.error).toContain('ENOENT');
  });

  it('refuses an app dir without a valid run.json without spawning', async () => {
    const bad = makeWorktree(`shop-poltergeist-2026-10-10-${Math.random().toString(36).slice(2)}`, {
      run: { script: 'nope' },
    });
    const r = await servers.ensure(bad, bad, 'a');
    expect(r.ok).toBe(false);
    expect(spawn).not.toHaveBeenCalled();
  });

  it('stopAll kills every running server', async () => {
    answer();
    const p = servers.ensure(wt, wt, 'a');
    await vi.advanceTimersByTimeAsync(500);
    await p;
    servers.stopAll();
    expect(killGroup).toHaveBeenCalledWith(child(0), 'SIGKILL');
    // The exit that follows a deliberate stop does not restart it.
    child(0).emit('exit', null, 'SIGKILL');
    await vi.advanceTimersByTimeAsync(1000);
    expect(spawn).toHaveBeenCalledTimes(1);
  });
});


describePosix('dev server sandboxing', () => {
  it('passes only an allowlisted environment', () => {
    const env = devServerBaseEnv({
      HOME: '/Users/me',
      LANG: 'en_GB.UTF-8',
      ANTHROPIC_API_KEY: 'sk-secret',
      GHOSTBRAIN_TOKEN: 'tok',
      AWS_SECRET_ACCESS_KEY: 'x',
      NODE_OPTIONS: '--require ./evil.js',
    });
    expect(env).toEqual({ HOME: '/Users/me', LANG: 'en_GB.UTF-8', NODE_ENV: 'development' });
  });

  it('pins dev-server frames to their own origin', () => {
    const csp = devServerCsp('http://127.0.0.1:5555');
    expect(csp).toContain("connect-src 'self' ws://127.0.0.1:5555");
    expect(csp).toContain("img-src 'self' data: blob:");
    expect(csp).not.toMatch(/https:\/\/\*|connect-src[^;]*https:/);
  });
});

describePosix('dev server sandbox', () => {
  it('wraps the argv in sandbox-exec with the worktree and vault as parameters', () => {
    const argv = sandboxArgv(['npm', 'run', 'dev'], {
      worktree: '/code/web-poltergeist-2026-10-10-x',
      appDir: '/code/web-poltergeist-2026-10-10-x/apps/web',
      home: '/Users/me',
      port: 5555,
      vault: '/Users/me/ghostbrain/vault',
    });
    expect(argv[0]).toBe(SANDBOX_EXEC);
    expect(argv[1]).toBe('-p');
    expect(argv[2]).toContain('(deny network*)');
    expect(argv[2]).toContain('(deny lsopen)');
    expect(argv[2]).not.toMatch(/unix-socket|Caches|\/private\/tmp/);
    expect(argv).toContain('PORT=5555');
    expect(argv[2]).toContain('(deny file-write*)');
    // writes: build caches only, never the sources or package.json
    expect(argv).toContain('APP_NM_VITE=/code/web-poltergeist-2026-10-10-x/apps/web/node_modules/.vite');
    expect(argv).toContain('SCRATCH=/code/web-poltergeist-2026-10-10-x/node_modules/.cache/poltergeist');
    expect(argv.some((a) => a.startsWith('WORKTREE='))).toBe(false);
    expect(argv).toContain('APP_RE=/code/web-poltergeist-2026-10-10-x/apps/web');
    expect(argv[2]).toContain('com.apple.mDNSResponder');
    expect(argv[2]).toContain('com.apple.pasteboard.1');
    expect(argv).toContain('VAULT=/Users/me/ghostbrain/vault');
    expect(argv).toContain('HOME_SSH=/Users/me/.ssh');
    expect(argv.slice(-3)).toEqual(['npm', 'run', 'dev']);
  });

  it('spawns through the wrapper', async () => {
    const calls: string[][] = [];
    const servers = new DevServers({
      wrap: (argv) => ['sandboxed', ...argv],
      spawn: ((cmd: string, args: string[]) => {
        calls.push([cmd, ...args]);
        throw new Error('stop here');
      }) as never,
      freePort: async () => 5555,
    });
    const wt = makeWorktree('web-poltergeist-2026-10-10-sandbox');
    const res = await servers.ensure(wt, wt);
    expect(res.ok).toBe(false);
    expect(calls[0]?.slice(0, 3)).toEqual(['sandboxed', 'npm', 'run']);
  });

  it('never runs unsandboxed: a wrapper failure fails the ensure', async () => {
    const spawn = vi.fn();
    const servers = new DevServers({
      wrap: () => {
        throw new SandboxUnavailableError('no sandbox here');
      },
      spawn: spawn as never,
      freePort: async () => 5555,
    });
    const wt = makeWorktree('web-poltergeist-2026-10-10-nosandbox');
    expect(await servers.ensure(wt, wt)).toEqual({ ok: false, error: 'no sandbox here' });
    expect(spawn).not.toHaveBeenCalled();
  });

  it('wipes the caches a sandboxed server could have poisoned, never through symlinks', () => {
    const wt = makeWorktree('web-poltergeist-2026-10-10-wipe');
    const outside = join(root, 'outside-keep');
    mkdirSync(outside, { recursive: true });
    writeFileSync(join(outside, 'keep.txt'), 'x');
    mkdirSync(join(wt, 'node_modules', '.vite', 'deps'), { recursive: true });
    writeFileSync(join(wt, 'node_modules', '.vite', 'deps', 'react.js'), 'evil()');
    mkdirSync(join(wt, '.next', 'server'), { recursive: true });
    writeFileSync(join(wt, 'vite.config.js.timestamp-1-abc.mjs'), 'evil()');
    symlinkSync(outside, join(wt, '.svelte-kit'));
    wipeSandboxCaches(wt, wt);
    expect(existsSync(join(wt, 'node_modules', '.vite'))).toBe(false);
    expect(existsSync(join(wt, '.next'))).toBe(false);
    expect(existsSync(join(wt, 'vite.config.js.timestamp-1-abc.mjs'))).toBe(false);
    expect(existsSync(join(outside, 'keep.txt'))).toBe(true);
    expect(existsSync(join(wt, 'package.json'))).toBe(true);
  });
});
