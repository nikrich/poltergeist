// Thin client over plugin.sidecar.request (resolves {ok,data}|{ok:false,error,status}).
import { normalizeMeta, serializeFile, slugify } from '../fountain/document.js';

export async function call(plugin, method, path, body) {
  if (typeof plugin?.sidecar?.request !== 'function') {
    throw new Error('plugin.sidecar.request is unavailable');
  }
  const r = await plugin.sidecar.request(method, path, body);
  if (!r || !r.ok) {
    const err = new Error(r?.error ?? `${method} ${path} failed`);
    err.status = r?.status;
    throw err;
  }
  return r.data;
}

export async function readScript(plugin, path) {
  try {
    const d = await call(plugin, 'GET', `/v1/notes?path=${encodeURIComponent(path)}`);
    return { meta: normalizeMeta(d.frontmatter), body: d.body ?? '' };
  } catch (e) {
    if (e.status === 404) return null;
    throw e;
  }
}

export async function writeScript(plugin, path, meta, body) {
  await call(plugin, 'PUT', '/v1/notes', { path, content: serializeFile(meta, body) });
}

export const listProjects = (plugin) => call(plugin, 'GET', '/v1/projects');

export async function listContexts(plugin) {
  const d = await call(plugin, 'GET', '/v1/vault/contexts');
  return Array.isArray(d?.contexts) ? d.contexts : [];
}

export async function createProject(plugin, context, name) {
  try {
    return await call(plugin, 'POST', '/v1/projects', { context, name });
  } catch (e) {
    if (e.status !== 409) throw e;
    const all = await listProjects(plugin);
    const hit = all.find((p) => p.context === context
      && (p.name.toLowerCase() === name.toLowerCase() || p.slug === slugify(name)));
    if (!hit) throw e;
    return hit;
  }
}
