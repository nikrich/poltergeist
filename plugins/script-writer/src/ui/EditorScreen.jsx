import { ArrowLeft, Download, Eye, FileText, Focus, Hash, ListTree, Moon, Sparkles, WandSparkles } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { readScript, writeScript } from '../api/backend.js';
import { draftKey, parseScriptPath, toFountain } from '../fountain/document.js';
import { typeAt, setType } from '../editor/commands.js';
import { insertSceneAfterCursor, toggleEmphasis } from '../editor/format.js';
import { characters as listCharacters, moveScene, scenes as listScenes } from '../fountain/outline.js';
import { parse } from '../fountain/parse.js';
import { isStaleProposal } from '../editor/proposal.js';
import { editorContext } from '../editor/context.js';
import { createEditor, jumpToLine, proposeEdit, setFocusMode } from '../editor/setup.js';
import { paginate } from '../paginate/paginate.js';
import { documentHtml, FONT_PLACEHOLDER } from '../render/pageHtml.js';
import { entryFor, markMissing, upsertEntry } from '../store/registry.js';
import { createSaver, shouldOfferDraft } from '../store/saver.js';
import { AiPanel } from './AiPanel.jsx';
import { CharacterList } from './CharacterList.jsx';
import { FormatBar } from './FormatBar.jsx';
import { PageView } from './PageView.jsx';
import { PolishDialog } from './PolishDialog.jsx';
import { PolishReview } from './PolishReview.jsx';
import { planPolishApply } from './polishApply.js';
import { SceneNav } from './SceneNav.jsx';
import { TitlePageFields } from './TitlePageFields.jsx';
import { useUiSettings } from './useUiSettings.js';

const STATUS_TEXT = { saved: 'Saved', dirty: 'Unsaved', saving: 'Saving\u2026' };
const MIRROR_MS = 300;

export function EditorScreen({ plugin, path, onBack, notify }) {
  const [loaded, setLoaded] = useState(null); // {meta, body}
  const [meta, setMeta] = useState(null);
  const [ui, patchUi] = useUiSettings(plugin);
  const [status, setStatus] = useState({ s: 'saved' });
  const [elements, setElements] = useState([]);
  const [cursorLine, setCursorLine] = useState(0);
  const [cursorType, setCursorType] = useState(null);
  const [draft, setDraft] = useState(null);
  const [titleEdit, setTitleEdit] = useState(null);
  const [menu, setMenu] = useState(false);
  const [aiFocus, setAiFocus] = useState(0);
  const [polish, setPolish] = useState(null); // null | {stage:'dialog'|'review', startText, result?}
  const hostRef = useRef(null);
  const viewRef = useRef(null);
  const metaRef = useRef(null);
  const saverRef = useRef(null);
  const analyzeTimer = useRef(null);
  const mirror = useRef({ timer: null, text: null });
  const key = draftKey(path);
  const slug = parseScriptPath(path)?.slug ?? 'screenplay';

  // Load the script (and any newer unsaved draft).
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const s = await readScript(plugin, path);
        if (!live) return;
        if (!s) {
          await markMissing(plugin.settings, path);
          notify('That script is no longer in the vault \u2014 marked missing.', 'error');
          onBack();
          return;
        }
        metaRef.current = s.meta;
        setMeta(s.meta);
        setLoaded(s);
        const d = await plugin.ipc.invoke('draft-read', key).catch(() => null);
        if (live && shouldOfferDraft(d, s.meta, s.body)) setDraft(d);
      } catch (e) {
        notify(`Could not open script: ${e.message}`, 'error');
        onBack();
      }
    })();
    return () => { live = false; };
  }, [plugin, path]); // eslint-disable-line react-hooks/exhaustive-deps

  const analyzeSoon = useCallback((text) => {
    clearTimeout(analyzeTimer.current);
    analyzeTimer.current = setTimeout(() => setElements(parse(text)), 400);
  }, []);

  // Saver: one per opened script.
  useEffect(() => {
    if (!loaded) return undefined;
    const saver = createSaver({
      save: async (body) => {
        const next = { ...metaRef.current, updated: new Date().toISOString() };
        await writeScript(plugin, path, next, body);
        metaRef.current = next;
        const pages = paginate(parse(body), { sceneNumbers: next.scene_numbers }).length;
        await upsertEntry(plugin.settings, entryFor(path, next, pages));
        await plugin.ipc.invoke('draft-clear', key).catch(() => {});
      },
      mirror: (body) => plugin.ipc.invoke('draft-write', { key, content: body, savedAt: new Date().toISOString() }),
      onStatus: (s, info) => setStatus({ s, info }),
    });
    saverRef.current = saver;
    const onWindowBlur = () => saver.flush();
    window.addEventListener('blur', onWindowBlur);
    return () => {
      window.removeEventListener('blur', onWindowBlur);
      saver.flush().finally(() => saver.dispose());
    };
  }, [loaded, plugin, path, key]);

  // Mirror every change to the local draft on a short debounce, independent of
  // the saver, so quitting mid-idle loses at most MIRROR_MS of typing. Safe after
  // a save: a mirror equal to the saved body is never offered (shouldOfferDraft).
  const writeMirror = useCallback(() => {
    const m = mirror.current;
    clearTimeout(m.timer);
    m.timer = null;
    if (m.text === null) return;
    const content = m.text;
    m.text = null;
    plugin.ipc.invoke('draft-write', { key, content, savedAt: new Date().toISOString() }).catch(() => {});
  }, [plugin, key]);
  const mirrorSoon = useCallback((text) => {
    const m = mirror.current;
    m.text = text;
    clearTimeout(m.timer);
    m.timer = setTimeout(writeMirror, MIRROR_MS);
  }, [writeMirror]);

  // CodeMirror view.
  useEffect(() => {
    if (!loaded || !hostRef.current) return undefined;
    const view = createEditor({
      parent: hostRef.current,
      doc: loaded.body,
      onDocChange: (text) => { saverRef.current?.change(text); mirrorSoon(text); analyzeSoon(text); },
      onCursorLine: (line0, type) => { setCursorLine(line0); setCursorType(type); },
      onSave: () => saverRef.current?.flush(),
      onToggleFocus: () => patchUi({ focus: !viewRef.current?.swFocus }),
      onAi: () => { patchUi({ panel: 'ai' }); setAiFocus((n) => n + 1); },
    });
    viewRef.current = view;
    setCursorType(typeAt(view.state, view.state.doc.lineAt(view.state.selection.main.head).number));
    setElements(parse(loaded.body));
    view.focus();
    return () => { clearTimeout(analyzeTimer.current); writeMirror(); view.destroy(); viewRef.current = null; };
  }, [loaded, analyzeSoon, mirrorSoon, writeMirror, patchUi]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.swFocus = ui.focus;
    setFocusMode(view, ui.focus);
  }, [ui.focus, loaded]);

  const pages = useMemo(() => paginate(elements, { sceneNumbers: meta?.scene_numbers }), [elements, meta?.scene_numbers]);
  const sceneList = useMemo(() => listScenes(elements), [elements]);
  const charList = useMemo(() => listCharacters(elements), [elements]);

  const jump = (line0) => viewRef.current && jumpToLine(viewRef.current, line0);
  const withView = (fn) => () => { const v = viewRef.current; if (v) { fn(v); v.focus(); } };
  const getContext = useCallback(() => editorContext(viewRef.current.state), []);
  const onPropose = useCallback((p) => {
    const v = viewRef.current;
    if (!v) return;
    if (isStaleProposal(v.state, p)) {
      notify('The script changed while the AI was working \u2014 run it again.', 'error');
      return;
    }
    proposeEdit(v, { from: p.from, to: p.to, text: p.text, mode: p.mode, label: p.label });
  }, [notify]);
  const onSetType = (type) => withView((v) => setType(type)(v))();
  const onEmphasis = (kind) => withView((v) => toggleEmphasis(kind)(v))();
  const onNewScene = withView((v) => insertSceneAfterCursor(v));
  const touch = () => viewRef.current && saverRef.current?.change(viewRef.current.state.doc.toString());
  const updateMeta = (patch) => {
    const next = { ...metaRef.current, ...patch };
    metaRef.current = next;
    setMeta(next);
    touch();
  };

  function onMoveScene(from, to) {
    const view = viewRef.current;
    const text = view.state.doc.toString();
    const next = moveScene(text, from, to);
    if (next !== text) view.dispatch({ changes: { from: 0, to: text.length, insert: next }, userEvent: 'move.scene' });
  }

  function restoreDraft() {
    const view = viewRef.current;
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: draft.content } });
    setDraft(null);
    notify('Unsaved draft restored.');
  }

  function applyPolish(text) {
    const view = viewRef.current;
    const current = view.state.doc.toString();
    const plan = planPolishApply({ current, startText: polish.startText, text });
    setPolish(null);
    if (plan === 'stale') {
      notify('The script changed while polishing \u2014 run Polish again so nothing you typed is overwritten.', 'error');
      return;
    }
    if (plan === 'noop') {
      notify('Nothing changed.');
      return;
    }
    view.dispatch({ changes: { from: 0, to: current.length, insert: text }, userEvent: 'input.polish' });
    notify('Polish applied \u2014 \u2318Z to undo.');
  }

  async function exportPdf() {
    setMenu(false);
    try {
      await saverRef.current?.flush();
      const body = viewRef.current.state.doc.toString();
      const html = documentHtml({ meta: metaRef.current, pages: paginate(parse(body), { sceneNumbers: metaRef.current.scene_numbers }), paper: ui.paper, fontBase: FONT_PLACEHOLDER });
      const r = await plugin.ipc.invoke('export-pdf', { html, defaultName: slug, paper: ui.paper });
      if (r?.path) notify(`PDF saved to ${r.path}`);
    } catch (e) {
      notify(`PDF export failed: ${e.message}`, 'error');
    }
  }

  async function exportFountain() {
    setMenu(false);
    try {
      const content = toFountain(metaRef.current, viewRef.current.state.doc.toString());
      const r = await plugin.ipc.invoke('export-file', { defaultName: slug, ext: 'fountain', content });
      if (r?.path) notify(`Fountain saved to ${r.path}`);
    } catch (e) {
      notify(`Export failed: ${e.message}`, 'error');
    }
  }

  if (!loaded || !meta) return <div className="sw-lib sw-muted">Opening&hellip;</div>;
  const statusLabel = status.s === 'error'
    ? `Unsaved \u2014 retrying in ${Math.round((status.info?.retryInMs ?? 0) / 1000)}s`
    : STATUS_TEXT[status.s];

  return (
    <>
      <div className="sw-bar">
        <button type="button" className="sw-btn" onClick={onBack} title="Library"><ArrowLeft size={14} /></button>
        <span className="sw-title" onClick={() => setTitleEdit(meta)} title="Edit title page">{meta.title}</span>
        <span className="sw-grow" />
        <span className="sw-muted">{pages.length} pp &middot; ~{pages.length} min</span>
        <span className={`sw-status${status.s === 'error' ? ' sw-err' : ''}`} title={status.info?.message ?? ''}>{statusLabel}</span>
        <button type="button" className={`sw-btn${ui.sceneNav ? ' sw-on' : ''}`} onClick={() => patchUi({ sceneNav: !ui.sceneNav })} title="Scenes & characters"><ListTree size={14} /></button>
        <button type="button" className={`sw-btn${ui.panel === 'page' ? ' sw-on' : ''}`} onClick={() => patchUi({ panel: ui.panel === 'page' ? null : 'page' })} title="Page view"><Eye size={14} /></button>
        <button type="button" className={`sw-btn${ui.panel === 'ai' ? ' sw-on' : ''}`} onClick={() => patchUi({ panel: ui.panel === 'ai' ? null : 'ai' })} title={'AI co-writer (\u2318K)'}><Sparkles size={14} /></button>
        <button type="button" className={`sw-btn${meta.scene_numbers ? ' sw-on' : ''}`} onClick={() => updateMeta({ scene_numbers: !meta.scene_numbers })} title="Scene numbers"><Hash size={14} /></button>
        <button type="button" className={`sw-btn${ui.focus ? ' sw-on' : ''}`} onClick={() => patchUi({ focus: !ui.focus })} title={'Focus mode (\u2318\u21e7F)'}><Focus size={14} /></button>
        <button type="button" className={`sw-btn${ui.dark ? ' sw-on' : ''}`} onClick={() => patchUi({ dark: !ui.dark })} title="Dark page"><Moon size={14} /></button>
        <select className="sw-btn" value={ui.paper} onChange={(e) => patchUi({ paper: e.target.value })} title="Paper size">
          <option value="letter">US Letter</option>
          <option value="a4">A4</option>
        </select>
        <button type="button" className="sw-btn" onClick={() => setPolish({ stage: 'dialog', startText: viewRef.current.state.doc.toString() })} title="Polish the whole script with AI"><WandSparkles size={14} />Polish</button>
        <div className="sw-menu">
          <button type="button" className="sw-btn" onClick={() => setMenu(!menu)}><Download size={14} />Export</button>
          {menu && (
            <div className="sw-menu-list">
              <button type="button" onClick={exportPdf}>PDF</button>
              <button type="button" onClick={exportFountain}><FileText size={12} /> Fountain</button>
            </div>
          )}
        </div>
      </div>
      {draft && (
        <div className="sw-banner">
          <span>An unsaved draft from {new Date(draft.savedAt).toLocaleString()} was found.</span>
          <span className="sw-grow" />
          <button type="button" className="sw-btn sw-primary" onClick={restoreDraft}>Restore</button>
          <button type="button" className="sw-btn" onClick={() => { plugin.ipc.invoke('draft-clear', key).catch(() => {}); setDraft(null); }}>Discard</button>
        </div>
      )}
      <FormatBar currentType={cursorType} onSetType={onSetType} onEmphasis={onEmphasis} onNewScene={onNewScene} />
      <div className="sw-body">
        {ui.sceneNav && (
          <aside className="sw-side">
            <SceneNav scenes={sceneList} cursorLine={cursorLine} onJump={jump} onMove={onMoveScene} onAdd={onNewScene} />
            <CharacterList characters={charList} onJump={jump} />
          </aside>
        )}
        <main className={`sw-main${ui.dark ? ' sw-dark' : ''}`}>
          <div className="sw-sheet" ref={hostRef} />
        </main>
        {ui.panel === 'page' && (
          <aside className="sw-right"><PageView meta={meta} pages={pages} paper={ui.paper} /></aside>
        )}
        {ui.panel === 'ai' && (
          <aside className="sw-right sw-right-ai">
            <AiPanel plugin={plugin} scriptPath={path} getContext={getContext} onPropose={onPropose} notify={notify} focusToken={aiFocus} />
          </aside>
        )}
      </div>
      {titleEdit && (
        <div className="sw-modal" role="dialog" aria-label="Title page">
          <div className="sw-dialog">
            <h2 style={{ marginTop: 0 }}>Title page</h2>
            <TitlePageFields value={titleEdit} onChange={setTitleEdit} />
            <div className="sw-row">
              <button type="button" className="sw-btn" onClick={() => setTitleEdit(null)}>Cancel</button>
              <button type="button" className="sw-btn sw-primary" onClick={() => { updateMeta(titleEdit); setTitleEdit(null); }}>Save</button>
            </div>
          </div>
        </div>
      )}
      {polish?.stage === 'dialog' && (
        <PolishDialog plugin={plugin} text={polish.startText} onCancel={() => setPolish(null)}
          onDone={(result) => setPolish((p) => ({ ...p, stage: 'review', result }))} />
      )}
      {polish?.stage === 'review' && <PolishReview result={polish.result} onApply={applyPolish} onClose={() => setPolish(null)} />}
    </>
  );
}
