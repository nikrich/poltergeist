import { mkdtemp, readFile, stat, chmod, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { installCliShim } from '../cli-shim';

// The CLI shim is a darwin-only feature (the gb:cli:install handler gates on
// process.platform). These tests exercise POSIX semantics Windows doesn't
// have: ':'-delimited PATH, and directory write permission via chmod 0444.
describe.skipIf(process.platform === 'win32')('installCliShim', () => {
  it('writes an executable wrapper into the first writable candidate', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'shim-'));
    const result = await installCliShim({
      binaryPath: '/Applications/Poltergeist.app/Contents/Resources/sidecar/ghostbrain-api/ghostbrain-api',
      candidates: [join(dir, 'bin')],
      pathEnv: `${join(dir, 'bin')}:/usr/bin`,
    });

    expect(result.path).toBe(join(dir, 'bin', 'poltergeist'));
    expect(result.onPath).toBe(true);
    const body = await readFile(result.path, 'utf8');
    expect(body).toBe(
      '#!/bin/sh\nexec "/Applications/Poltergeist.app/Contents/Resources/sidecar/ghostbrain-api/ghostbrain-api" "$@"\n',
    );
    const mode = (await stat(result.path)).mode & 0o777;
    expect(mode).toBe(0o755);
  });

  it('falls through to the next candidate when a dir is unwritable', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'shim-'));
    const locked = join(dir, 'locked');
    await mkdir(locked);
    await chmod(locked, 0o444);
    const fallback = join(dir, 'fallback');

    const result = await installCliShim({
      binaryPath: '/x/ghostbrain-api',
      candidates: [locked, fallback],
      pathEnv: '/usr/bin',
    });

    expect(result.path).toBe(join(fallback, 'poltergeist'));
    expect(result.onPath).toBe(false);
  });
});
