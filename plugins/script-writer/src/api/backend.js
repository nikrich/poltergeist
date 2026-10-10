// Thin client over plugin.sidecar.request (resolves {ok,data}|{ok:false,error,status}).
import { normalizeMeta, serializeFile, slugify } from '../fountain/document.js';

export async function call(plugin, method, path, body, opts) {
  if (typeof plugin?.sidecar?.request !== 'function') {
    throw new Error('plugin.sidecar.request is unavailable');
  }
  const r = opts === undefined
    ? await plugin.sidecar.request(method, path, body)
    : await plugin.sidecar.request(method, path, body, opts);
  if (!r || !r.ok) {
    const err = new Error(r?.error ?? `${method} ${path} failed`);
    err.status = r?.status;
    throw err;
  }
  return r.data;
}

// The sidecar refuses a plugin's rewrite of an existing note without If-Match
// (428) and a stale one (409), so track per plugin, per path, the etag of the
// version last read or written; consecutive autosaves chain through the PUT's etag.
const etagsByPlugin = new WeakMap();
function etags(plugin) {
  let m = etagsByPlugin.get(plugin);
  if (!m) {
    m = new Map();
    etagsByPlugin.set(plugin, m);
  }
  return m;
}
function rememberEtag(plugin, path, etag) {
  if (typeof etag === 'string' && etag) etags(plugin).set(path, etag);
  else etags(plugin).delete(path);
}

export async function readScript(plugin, path) {
  try {
    const d = await call(plugin, 'GET', `/v1/notes?path=${encodeURIComponent(path)}`);
    rememberEtag(plugin, path, d.etag);
    return { meta: normalizeMeta(d.frontmatter), body: d.body ?? '' };
  } catch (e) {
    if (e.status === 404) {
      etags(plugin).delete(path);
      return null;
    }
    throw e;
  }
}

export async function writeScript(plugin, path, meta, body) {
  const etag = etags(plugin).get(path);
  const d = await call(plugin, 'PUT', '/v1/notes', { path, content: serializeFile(meta, body) },
    etag ? { ifMatch: etag } : undefined);
  rememberEtag(plugin, path, d?.etag);
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
