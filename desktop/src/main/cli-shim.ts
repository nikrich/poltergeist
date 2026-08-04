import { chmod, mkdir, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { delimiter, join } from 'node:path';

export interface CliShimOptions {
  /** Absolute path to the bundled ghostbrain-api binary. */
  binaryPath: string;
  /** Install locations, tried in order. Defaults to /usr/local/bin then ~/.local/bin. */
  candidates?: string[];
  /** PATH to check membership against. Defaults to process.env.PATH. */
  pathEnv?: string;
}

export interface CliShimResult {
  /** Where the `poltergeist` wrapper was written. */
  path: string;
  /** Whether its directory is already on PATH. */
  onPath: boolean;
}

/**
 * Write a `poltergeist` shell wrapper that execs the bundled sidecar binary,
 * so connector auth / fetch commands need no Python install (VS Code's
 * "install code command" pattern). macOS-only for now.
 */
export async function installCliShim(opts: CliShimOptions): Promise<CliShimResult> {
  const candidates = opts.candidates ?? ['/usr/local/bin', join(homedir(), '.local', 'bin')];
  const script = `#!/bin/sh\nexec "${opts.binaryPath}" "$@"\n`;
  let lastErr: unknown = new Error('no install candidates');
  for (const dir of candidates) {
    const target = join(dir, 'poltergeist');
    try {
      await mkdir(dir, { recursive: true });
      await writeFile(target, script, 'utf8');
      await chmod(target, 0o755);
      const pathEnv = opts.pathEnv ?? process.env.PATH ?? '';
      return { path: target, onPath: pathEnv.split(delimiter).includes(dir) };
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr;
}
