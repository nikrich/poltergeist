import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { cp, mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { manifestSchema, type PluginRecord } from '../../shared/plugin-types';
import * as store from './store';

// Install = validate + copy. NEVER runs npm, build scripts, or hooks —
// plugins ship pre-built dist/ (spec: "pre-built is a hard rule").

const execFileP = promisify(execFile);

// https and ssh for real installs; file:// covers local installs and tests —
// this is a desktop app installing code the user already trusts.
const URL_ALLOW = /^(https:\/\/|git@|file:\/\/)/;

async function readManifest(dir: string) {
  const raw = await readFile(join(dir, 'manifest.json'), 'utf-8');
  const parsed = manifestSchema.safeParse(JSON.parse(raw));
  if (!parsed.success) {
    throw new Error(`invalid manifest: ${parsed.error.issues[0]?.message ?? 'validation failed'}`);
  }
  return parsed.data;
}

async function copyIn(src: string, pluginsRoot: string): Promise<PluginRecord> {
  const manifest = await readManifest(src);
  const dest = join(pluginsRoot, manifest.id);
  if (existsSync(dest)) {
    throw new Error(`plugin "${manifest.id}" is already installed — uninstall it first`);
  }
  await cp(src, dest, {
    recursive: true,
    filter: (p) => !p.split('/').includes('.git'),
  });
  store.setEnabled(manifest.id, true);
  return { id: manifest.id, dir: dest, manifest, state: 'enabled' };
}

export async function installFromFolder(src: string, pluginsRoot: string): Promise<PluginRecord> {
  const s = await stat(src).catch(() => null);
  if (!s?.isDirectory()) throw new Error(`not a directory: ${src}`);
  return copyIn(src, pluginsRoot);
}

async function cloneToTmp(
  url: string,
  subdir: string | undefined,
): Promise<{ tmp: string; src: string }> {
  if (!URL_ALLOW.test(url)) {
    throw new Error('url must start with https://, git@, or file://');
  }
  const tmp = await mkdtemp(join(tmpdir(), 'gb-plugin-clone-'));
  await execFileP('git', ['clone', '--depth', '1', '--single-branch', url, tmp], {
    timeout: 120_000,
  });
  const src = subdir ? join(tmp, subdir) : tmp;
  const s = await stat(src).catch(() => null);
  if (!s?.isDirectory()) throw new Error(`subdirectory not found in repo: ${subdir}`);
  return { tmp, src };
}

export async function installFromGit(
  url: string,
  subdir: string | undefined,
  pluginsRoot: string,
): Promise<PluginRecord> {
  const { tmp, src } = await cloneToTmp(url, subdir);
  try {
    return await copyIn(src, pluginsRoot);
  } finally {
    await rm(tmp, { recursive: true, force: true });
  }
}

// Update = re-fetch over an existing install. Unlike copyIn, it *requires*
// the destination to exist and replaces it, preserving the store's enabled
// flag and per-plugin data (no store.setEnabled/forget calls here).
export async function updateFromGit(
  url: string,
  subdir: string | undefined,
  expectedId: string,
  pluginsRoot: string,
): Promise<PluginRecord> {
  const { tmp, src } = await cloneToTmp(url, subdir);
  try {
    const manifest = await readManifest(src);
    if (manifest.id !== expectedId) {
      throw new Error(
        `update fetched a different plugin id: expected "${expectedId}", got "${manifest.id}"`,
      );
    }
    const dest = join(pluginsRoot, expectedId);
    await rm(dest, { recursive: true, force: true });
    await cp(src, dest, {
      recursive: true,
      filter: (p) => !p.split('/').includes('.git'),
    });
    return { id: manifest.id, dir: dest, manifest, state: 'enabled' };
  } finally {
    await rm(tmp, { recursive: true, force: true });
  }
}

export async function uninstall(id: string, pluginsRoot: string): Promise<void> {
  await rm(join(pluginsRoot, id), { recursive: true, force: true });
  store.forget(id);
}
