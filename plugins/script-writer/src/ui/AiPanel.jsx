import { Send, Sparkles, Trash2 } from 'lucide-react';
import { Marked } from 'marked';
import { memo, useEffect, useRef, useState } from 'react';
import { BUDGETS, runLlm } from '../ai/llm.js';
import { ACTIONS, REWRITE_PRESETS, actionPrompt, askPrompt, outlineText } from '../ai/prompts.js';
import { retrieve, SCOPES } from '../ai/retrieve.js';
import { checkFountain } from '../ai/validate.js';
import { draftKey } from '../fountain/document.js';

// LLM and vault content is untrusted: markdown renders, raw HTML, images and
// non-http(s) links do not. http(s) links become buttons opened by the host.
const escapeAttr = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const md = new Marked({
  renderer: {
    html: () => '',
    link(href, title, text) {
      const stripped = String(text ?? '').replace(/<[^>]*>/g, '');
      if (/^https?:\/\//i.test(String(href ?? ''))) {
        return `<button type="button" class="sw-link" data-href="${escapeAttr(href)}">${stripped}</button>`;
      }
      return stripped;
    },
    image: (href, title, text) => escapeAttr(text),
    text: (text) => String(text).replace(/\[(\d{1,2})\]/g, '<button type="button" class="sw-cite" data-n="$1">[$1]</button>'),
  },
});

const MAX_THREAD = 100;
const FENCE = '```';
const SCOPE_LABEL = { project: 'This project', context: 'This context', vault: 'Whole vault' };
const WIDENED = 'Nothing in this project matched \u2014 searched the whole context.';

export function renderAnswer(text) {
  return String(md.parse(String(text ?? '')));
}

const MessageBody = memo(function MessageBody({ text }) {
  return <div className="sw-md" dangerouslySetInnerHTML={{ __html: renderAnswer(text) }} />;
});

const slim = (sources) => sources.map(({ n, path, title, snippet, content }) => ({
  n, path, title, snippet, ...(content ? { content: content.slice(0, 1500) } : {}),
}));
const plainLabel = (a) => a.label.replace('\u2026', '');

export function AiPanel({ plugin, scriptPath, getContext, onPropose, notify, focusToken }) {
  const key = draftKey(scriptPath);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [scope, setScope] = useState('project');
  const [busy, setBusy] = useState(null);
  const [actionId, setActionId] = useState('continue');
  const [direction, setDirection] = useState('');
  const [openSource, setOpenSource] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const mounted = useRef(true);
  const latest = useRef([]);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const action = ACTIONS.find((a) => a.id === actionId);

  useEffect(() => {
    let live = true;
    setLoaded(false);
    plugin.ipc.invoke('thread-read', key).then((m) => {
      if (live && Array.isArray(m)) { latest.current = m; setMessages(m); }
    }).catch(() => {}).finally(() => { if (live) setLoaded(true); });
    return () => { live = false; };
  }, [plugin, key]);
  useEffect(() => () => { mounted.current = false; }, []);
  useEffect(() => { if (loaded) inputRef.current?.focus(); }, [focusToken, loaded]);
  useEffect(() => { const l = listRef.current; if (l) l.scrollTop = l.scrollHeight; }, [messages, busy]);

  const push = (msgs) => {
    if (!mounted.current) return;
    const kept = msgs.slice(-MAX_THREAD);
    latest.current = kept;
    setMessages(kept);
    plugin.ipc.invoke('thread-write', { key, messages: kept }).catch(() => {});
  };

  async function ask(e) {
    e?.preventDefault?.();
    const question = input.trim();
    if (!question || busy || !loaded) return;
    const history = latest.current;
    const withQ = [...history, { role: 'user', text: question }];
    push(withQ);
    setInput('');
    setBusy('Searching your vault\u2026');
    try {
      const ctx = getContext();
      const r = await retrieve(plugin, { query: question, scriptPath, scope });
      setBusy('Thinking\u2026');
      const { system, prompt } = askPrompt({ question, outline: outlineText(ctx.elements), scene: ctx.scene.text, sources: r.sources, history });
      const out = await runLlm(plugin, { system, prompt, budgetUsd: BUDGETS.ask });
      push([...withQ, { role: 'assistant', text: out.text, sources: slim(r.sources), ...(r.widened ? { note: WIDENED } : {}) }]);
    } catch (err) {
      push([...withQ, { role: 'assistant', text: '', error: err.message }]);
    } finally {
      setBusy(null);
    }
  }

  async function runAction() {
    if (busy || !loaded) return;
    if (action.needsDirection && !direction.trim()) { notify('Say how to rewrite it, or pick a preset.', 'error'); return; }
    const request = { role: 'user', text: `${plainLabel(action)}${direction.trim() && action.needsDirection ? `: ${direction.trim()}` : ''}` };
    const base = [...latest.current, request];
    setBusy(`${plainLabel(action)}\u2026`);
    try {
      const ctx = getContext();
      const target = ctx.selection.text.trim() ? ctx.selection : ctx.scene;
      if (!target.text.trim()) { notify('Put the cursor in a scene or select some text first.', 'error'); return; }
      const r = await retrieve(plugin, { query: target.text.slice(0, 500), scriptPath, scope });
      const { system, prompt, jsonSchema } = actionPrompt({
        action, direction: action.needsDirection ? direction.trim() : '', target: target.text, outline: outlineText(ctx.elements), sources: r.sources,
      });
      const out = await runLlm(plugin, { system, prompt, jsonSchema, budgetUsd: BUDGETS.action });
      if (action.edits === 'none') {
        push([...base, { role: 'assistant', text: out.text, sources: slim(r.sources) }]);
        return;
      }
      const check = checkFountain(target.text, out.structured?.fountain, { minKeep: 0, requireStructure: action.edits === 'replace' });
      if (!check.ok) {
        push([...base, { role: 'assistant', text: `That suggestion wasn't usable screenplay text (${check.reason}), so it wasn't applied.${check.text ? `\n\n${FENCE}\n${check.text}\n${FENCE}` : ''}` }]);
        return;
      }
      const insert = action.edits === 'insert';
      const lead = target.text.match(/^\s*/)[0];
      const trail = target.text.match(/\s*$/)[0];
      onPropose({
        from: insert ? target.to : target.from, to: target.to, text: insert ? check.text : lead + check.text + trail, mode: action.edits, label: plainLabel(action),
        original: target.text, anchorFrom: target.from,
      });
      push([...base, { role: 'assistant', text: out.structured?.notes || 'Suggestion shown in the script \u2014 accept or reject it there.' }]);
    } catch (err) {
      push([...base, { role: 'assistant', text: '', error: err.message }]);
    } finally {
      setBusy(null);
    }
  }

  function onListClick(e) {
    const link = e.target?.closest?.('.sw-link');
    if (link) { plugin.openExternal?.(link.dataset.href); return; }
    const n = e.target?.dataset?.n;
    const holder = e.target?.closest?.('[data-msg]');
    if (!n || !holder) return;
    const id = `${holder.dataset.msg}:${n}`;
    setOpenSource((cur) => (cur === id ? null : id));
  }

  return (
    <div className="sw-ai">
      <div className="sw-ai-head">
        <Sparkles size={14} /><strong>AI co-writer</strong><span className="sw-grow" />
        <select className="sw-btn" value={scope} onChange={(e) => setScope(e.target.value)} title="Where to look in your vault">
          {SCOPES.map((s) => <option key={s} value={s}>{SCOPE_LABEL[s]}</option>)}
        </select>
        <button type="button" className="sw-btn" title="Clear conversation" disabled={!loaded || !!busy} onClick={() => push([])}><Trash2 size={14} /></button>
      </div>
      <div className="sw-ai-actions">
        <select className="sw-btn" value={actionId} onChange={(e) => setActionId(e.target.value)} title="Works on the selection, or the scene at the cursor">
          {ACTIONS.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
        </select>
        <button type="button" className="sw-btn sw-primary" disabled={!!busy || !loaded} onClick={runAction}>Run</button>
        {action.needsDirection && (
          <div className="sw-ai-dir">
            <input value={direction} onChange={(e) => setDirection(e.target.value)} placeholder={'How? e.g. tighter, darker\u2026'} />
            <div className="sw-chips">
              {REWRITE_PRESETS.map((p) => <button type="button" key={p} className="sw-chip" onClick={() => setDirection(p)}>{p}</button>)}
            </div>
          </div>
        )}
      </div>
      <div className="sw-ai-list" ref={listRef} onClick={onListClick}>
        {messages.length === 0 && (
          <p className="sw-muted">Ask anything about your story &mdash; the AI searches this project&rsquo;s notes first. Or pick an action above to work on the scene at your cursor.</p>
        )}
        {messages.map((m, i) => {
          const open = openSource?.startsWith(`${i}:`) ? m.sources?.find((s) => String(s.n) === openSource.split(':')[1]) : null;
          return (
            <div key={i} data-msg={i} className={`sw-msg sw-msg-${m.role}`}>
              {m.role === 'user' && <div>{m.text}</div>}
              {m.role === 'assistant' && m.error && <div className="sw-status sw-err">{m.error}</div>}
              {m.role === 'assistant' && !m.error && <MessageBody text={m.text} />}
              {m.note && <div className="sw-muted">{m.note}</div>}
              {open && (
                <div className="sw-source">
                  <strong>[{open.n}] {open.title}</strong>
                  <div className="sw-muted">{open.path}</div>
                  <pre>{open.content ?? open.snippet}</pre>
                </div>
              )}
            </div>
          );
        })}
        {busy && <div className="sw-muted sw-busy">{busy}</div>}
      </div>
      <form className="sw-ai-input" onSubmit={ask}>
        <textarea ref={inputRef} rows={3} disabled={!loaded} value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); } }}
          placeholder={'Ask about your story, characters, research\u2026'} />
        <button type="submit" className="sw-btn sw-primary" disabled={!!busy || !input.trim()} title="Ask"><Send size={14} /></button>
      </form>
    </div>
  );
}
