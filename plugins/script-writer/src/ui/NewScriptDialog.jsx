import { useEffect, useState } from 'react';
import { createProject, listContexts, listProjects, readScript, writeScript } from '../api/backend.js';
import { DEFAULT_META, freeScriptPath, normalizeMeta } from '../fountain/document.js';
import { entryFor, upsertEntry } from '../store/registry.js';
import { TitlePageFields } from './TitlePageFields.jsx';

const NEW = '__new__';
const STARTER = 'FADE IN:\n\nINT. LOCATION - DAY\n\n';

export function NewScriptDialog({ plugin, initial, onCreate, onCancel }) {
  const [meta, setMeta] = useState(() => ({
    ...DEFAULT_META, draft_date: new Date().toISOString().slice(0, 10), ...(initial?.meta ?? {}),
  }));
  const [projects, setProjects] = useState([]);
  const [contexts, setContexts] = useState([]);
  const [projectKey, setProjectKey] = useState(NEW);
  const [newContext, setNewContext] = useState('');
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([listProjects(plugin), listContexts(plugin)]).then(([ps, cs]) => {
      const active = ps.filter((p) => !p.archived);
      setProjects(active);
      setContexts(cs);
      setNewContext(cs[0] ?? '');
      if (active.length) setProjectKey(`${active[0].context}/${active[0].slug}`);
    }).catch((e) => setError(`Could not load projects: ${e.message}`));
  }, [plugin]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      if (!meta.title.trim()) throw new Error('Give the script a title');
      let project = projects.find((p) => `${p.context}/${p.slug}` === projectKey);
      if (projectKey === NEW) {
        if (!newContext || !newName.trim()) throw new Error('Pick a context and name the project');
        project = await createProject(plugin, newContext, newName.trim());
      }
      const path = await freeScriptPath({
        context: project.context, project: project.slug, title: meta.title,
        exists: async (p) => (await readScript(plugin, p)) !== null,
      });
      const full = normalizeMeta({ ...meta, updated: new Date().toISOString() });
      await writeScript(plugin, path, full, initial?.body?.trim() ? initial.body : STARTER);
      await upsertEntry(plugin.settings, entryFor(path, full, 1));
      onCreate(path);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  const byContext = projects.reduce((acc, p) => ({ ...acc, [p.context]: [...(acc[p.context] ?? []), p] }), {});
  return (
    <div className="sw-modal" role="dialog" aria-label="New script">
      <div className="sw-dialog">
        <h2 style={{ marginTop: 0 }}>{initial ? 'Import script' : 'New script'}</h2>
        <label className="sw-field">
          <span className="sw-muted">Project</span>
          <select value={projectKey} onChange={(e) => setProjectKey(e.target.value)}>
            {Object.entries(byContext).map(([ctx, ps]) => (
              <optgroup key={ctx} label={ctx}>
                {ps.map((p) => <option key={p.id} value={`${p.context}/${p.slug}`}>{p.name}</option>)}
              </optgroup>
            ))}
            <option value={NEW}>+ New project&hellip;</option>
          </select>
        </label>
        {projectKey === NEW && (
          <div style={{ display: 'flex', gap: 8 }}>
            <label className="sw-field" style={{ flex: 1 }}>
              <span className="sw-muted">Context</span>
              <select value={newContext} onChange={(e) => setNewContext(e.target.value)}>
                {contexts.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label className="sw-field" style={{ flex: 2 }}>
              <span className="sw-muted">Project name</span>
              <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="The Long Night" />
            </label>
          </div>
        )}
        <TitlePageFields value={meta} onChange={setMeta} />
        {error && <div className="sw-status sw-err">{error}</div>}
        <div className="sw-row">
          <button type="button" className="sw-btn" onClick={onCancel} disabled={busy}>Cancel</button>
          <button type="button" className="sw-btn sw-primary" onClick={create} disabled={busy}>{busy ? 'Creating\u2026' : 'Create'}</button>
        </div>
      </div>
    </div>
  );
}
