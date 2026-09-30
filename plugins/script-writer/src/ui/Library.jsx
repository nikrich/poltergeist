import { Clapperboard, FileUp, Plus, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { fromFdx } from '../fdx/import.js';
import { fromFountain } from '../fountain/document.js';
import { loadRegistry, removeEntry } from '../store/registry.js';
import { NewScriptDialog } from './NewScriptDialog.jsx';

const when = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
};

export function Library({ plugin, onOpen, notify }) {
  const [entries, setEntries] = useState(null);
  const [dialog, setDialog] = useState(null); // null | {initial?}

  const reload = useCallback(() => loadRegistry(plugin.settings).then(setEntries).catch((e) => notify(e.message, 'error')), [plugin, notify]);
  useEffect(() => { reload(); }, [reload]);

  async function importScript() {
    try {
      const r = await plugin.ipc.invoke('import-file');
      if (!r || r.canceled) return;
      const parsed = /\.fdx$/i.test(r.name) ? fromFdx(r.content) : fromFountain(r.content);
      if (parsed.meta.title === 'Untitled') parsed.meta.title = r.name.replace(/\.[^.]+$/, '');
      setDialog({ initial: parsed });
    } catch (e) {
      notify(`Import failed: ${e.message}`, 'error');
    }
  }

  const sorted = [...(entries ?? [])].sort((a, b) => String(b.updated).localeCompare(String(a.updated)));
  return (
    <div className="sw-lib">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Clapperboard size={20} />
        <h1 style={{ margin: 0, fontSize: 20, flex: 1 }}>Scripts</h1>
        <button type="button" className="sw-btn" onClick={importScript}><FileUp size={14} />Import script</button>
        <button type="button" className="sw-btn sw-primary" onClick={() => setDialog({})}><Plus size={14} />New script</button>
      </div>
      {entries && sorted.length === 0 && <p className="sw-muted" style={{ marginTop: 24 }}>No scripts yet. Create one or import a .fountain or .fdx file.</p>}
      <div className="sw-grid">
        {sorted.map((e) => (
          <div key={e.path} className={`sw-card${e.missing ? ' sw-missing' : ''}`}
            onClick={() => !e.missing && onOpen(e.path)} role="button" tabIndex={0}
            onKeyDown={(ev) => ev.key === 'Enter' && !e.missing && onOpen(e.path)}>
            <h3>{e.title}</h3>
            <div className="sw-muted">{e.context} &middot; {e.project}</div>
            <div className="sw-muted">{e.pages ?? 0} pp &middot; {when(e.updated)}</div>
            {e.missing && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                <span className="sw-status sw-err">Missing from vault</span>
                <button type="button" className="sw-btn" onClick={async (ev) => { ev.stopPropagation(); setEntries(await removeEntry(plugin.settings, e.path)); }}>
                  <Trash2 size={14} />Remove
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
      {dialog && (
        <NewScriptDialog plugin={plugin} initial={dialog.initial}
          onCancel={() => setDialog(null)}
          onCreate={(path) => { setDialog(null); onOpen(path); }} />
      )}
    </div>
  );
}
