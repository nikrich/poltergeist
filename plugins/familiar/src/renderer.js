import { marked } from 'marked';
import { parseOpenLoops, renderOpenLoops, parseDecisions } from './lib/trackers.js';
import { statusLine, toggleLoop } from './lib/ui.js';

// Briefing bodies come from LLM/connector content and must be treated as
// untrusted (prompt-injection defense): markdown still renders, but any raw
// HTML tokens (block or inline) are dropped instead of passed through.
marked.use({ renderer: { html: () => '' } });

const LOOPS_PATH = 'Familiar/open-loops.md';
const DECISIONS_PATH = 'Familiar/decisions.md';

function tv(theme, name, fallback) {
  return theme?.[name] || fallback;
}

async function readNote(api, path) {
  const r = await api.sidecar.request('GET', `/v1/notes?path=${encodeURIComponent(path)}`);
  return r.ok ? r.data.body : null;
}

export function mount(el, api) {
  el.innerHTML = '';
  const t = api.theme || {};
  const paper = tv(t, '--paper', '#fff');
  const vellum = tv(t, '--vellum', '#faf9f6');
  const hairline = tv(t, '--hairline', '#e2e0da');
  const hairline2 = tv(t, '--hairline-2', '#ece9e2');
  const ink0 = tv(t, '--ink-0', 'inherit');
  const ink1 = tv(t, '--ink-1', '#444');
  const ink2 = tv(t, '--ink-2', '#888');
  const neon = tv(t, '--neon', '#2563eb');
  const oxblood = tv(t, '--oxblood', '#9a3324');

  const root = document.createElement('div');
  root.style.cssText = `padding:24px;max-width:860px;margin:0 auto;color:${ink0};font-size:14px;background:${paper};line-height:1.5;`;
  el.appendChild(root);

  const header = document.createElement('div');
  header.style.cssText = `display:flex;align-items:center;gap:12px;margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid ${hairline};`;
  const title = document.createElement('h1');
  title.textContent = 'Familiar';
  title.style.cssText = 'font-size:20px;margin:0;flex:1;font-weight:600;';
  const status = document.createElement('span');
  status.style.cssText = `color:${ink2};font-size:12px;`;
  const runBtn = document.createElement('button');
  runBtn.textContent = 'Run now';
  runBtn.style.cssText = `border:1px solid ${neon};color:${neon};background:transparent;border-radius:6px;padding:6px 12px;font-size:12px;cursor:pointer;`;
  runBtn.onmouseenter = () => { runBtn.style.background = neon; runBtn.style.color = paper; };
  runBtn.onmouseleave = () => { runBtn.style.background = 'transparent'; runBtn.style.color = neon; };
  header.append(title, status, runBtn);
  root.appendChild(header);

  const sectionStyle = `background:${vellum};border:1px solid ${hairline};border-radius:8px;padding:16px;margin-bottom:16px;`;
  const sections = {
    briefing: document.createElement('section'),
    loops: document.createElement('section'),
    decisions: document.createElement('section'),
    history: document.createElement('section'),
    settings: document.createElement('section'),
  };
  for (const s of Object.values(sections)) {
    s.style.cssText = sectionStyle;
    root.appendChild(s);
  }

  async function refreshStatus() {
    const st = await api.ipc.invoke('status');
    const line = statusLine(st);
    status.textContent = line;
    status.style.color = line.includes('failed') ? oxblood : ink2;
    runBtn.disabled = st.running;
    runBtn.style.opacity = st.running ? '0.5' : '1';
    runBtn.style.cursor = st.running ? 'default' : 'pointer';
    return st;
  }

  async function renderBriefing(st) {
    const runs = (st.lastRuns ?? []).filter((r) => r.ok && r.briefingPath);
    const latest = runs[runs.length - 1];
    sections.briefing.innerHTML = '<h2 style="margin-top:0;font-size:15px;">Latest briefing</h2>';
    if (!latest) {
      sections.briefing.insertAdjacentHTML('beforeend', `<p style="color:${ink2};">No briefing yet — hit "Run now".</p>`);
      sections.history.innerHTML = '';
      return;
    }
    const body = await readNote(api, latest.briefingPath);
    sections.briefing.insertAdjacentHTML('beforeend', body ? marked.parse(body) : `<p style="color:${ink2};">(briefing note missing)</p>`);
    const older = runs.slice(0, -1).reverse();
    sections.history.innerHTML = '';
    if (older.length) {
      const heading = document.createElement('h2');
      heading.textContent = 'History';
      heading.style.cssText = 'margin-top:0;font-size:15px;';
      sections.history.appendChild(heading);
      for (const r of older) {
        const row = document.createElement('div');
        row.style.cssText = `padding:4px 0;border-top:1px solid ${hairline2};color:${ink1};`;
        row.textContent = r.briefingPath;
        sections.history.appendChild(row);
      }
    }
  }

  async function renderLoops() {
    const body = (await readNote(api, LOOPS_PATH)) ?? '';
    const { loops, unparsed } = parseOpenLoops(body);
    sections.loops.innerHTML = '<h2 style="margin-top:0;font-size:15px;">Open loops</h2>';
    for (const loop of loops.filter((l) => l.status !== 'dismissed')) {
      const row = document.createElement('div');
      row.style.cssText = `display:flex;gap:8px;align-items:baseline;padding:6px 0;border-top:1px solid ${hairline2};`;
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.checked = loop.status === 'done';
      const label = document.createElement('span');
      label.textContent = `${loop.text}${loop.owedTo ? ` — owed to ${loop.owedTo}` : ''}${loop.status === 'stale' ? ' (stale)' : ''}`;
      label.style.color = ink1;
      if (loop.status === 'done') label.style.textDecoration = 'line-through';
      if (loop.status === 'stale') label.style.color = oxblood;
      const dismiss = document.createElement('button');
      dismiss.textContent = 'dismiss';
      dismiss.style.cssText = `margin-left:auto;font-size:11px;background:none;border:none;color:${ink2};cursor:pointer;`;
      const save = async (updated) => {
        const fresh = parseOpenLoops((await readNote(api, LOOPS_PATH)) ?? '');
        const next = fresh.loops.map((l) => (l.id === updated.id ? updated : l));
        await api.sidecar.request('PUT', '/v1/notes', { path: LOOPS_PATH, content: renderOpenLoops(next, fresh.unparsed) });
        await renderLoops();
      };
      box.onchange = () => void save(toggleLoop(loop));
      dismiss.onclick = () => void save({ ...loop, status: 'dismissed' });
      row.append(box, label, dismiss);
      sections.loops.appendChild(row);
    }
    if (unparsed.length) {
      sections.loops.insertAdjacentHTML(
        'beforeend',
        `<p style="opacity:.6;color:${ink2};font-size:12px;">${unparsed.length} hand-edited line(s) preserved in the note.</p>`,
      );
    }
  }

  async function renderDecisionLog() {
    const body = (await readNote(api, DECISIONS_PATH)) ?? '';
    const list = parseDecisions(body);
    sections.decisions.innerHTML = '<h2 style="margin-top:0;font-size:15px;">Decisions</h2>';
    for (const d of list.slice().reverse()) {
      const row = document.createElement('div');
      row.style.cssText = `padding:4px 0;border-top:1px solid ${hairline2};color:${ink1};`;
      const date = document.createElement('strong');
      date.textContent = d.date;
      row.append(date, ` — ${d.text}`);
      sections.decisions.appendChild(row);
    }
  }

  function renderSettings(st) {
    const cfg = st.config;
    sections.settings.innerHTML = '<h2 style="margin-top:0;font-size:15px;">Settings</h2>';
    const form = document.createElement('div');
    form.style.cssText = `display:flex;gap:8px;align-items:center;flex-wrap:wrap;color:${ink1};`;
    const day = document.createElement('select');
    for (const d of ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']) {
      const o = document.createElement('option');
      o.value = d;
      o.textContent = d;
      o.selected = d === cfg.day;
      day.appendChild(o);
    }
    const hour = document.createElement('input');
    hour.type = 'number';
    hour.min = '0';
    hour.max = '23';
    hour.value = String(cfg.hour);
    hour.style.width = '56px';
    const model = document.createElement('select');
    for (const m of ['haiku', 'sonnet', 'opus']) {
      const o = document.createElement('option');
      o.value = m;
      o.textContent = m;
      o.selected = m === cfg.model;
      model.appendChild(o);
    }
    const budget = document.createElement('input');
    budget.type = 'number';
    budget.step = '10000';
    budget.value = String(cfg.budgetChars);
    budget.style.width = '96px';
    for (const field of [day, hour, model, budget]) {
      field.style.cssText += `border:1px solid ${hairline};border-radius:4px;padding:4px 6px;background:${paper};color:${ink0};`;
    }
    const save = document.createElement('button');
    save.textContent = 'Save';
    save.style.cssText = `border:1px solid ${hairline};border-radius:4px;padding:4px 10px;background:${paper};color:${ink0};cursor:pointer;`;
    save.onclick = async () => {
      await api.ipc.invoke('config:set', {
        day: day.value,
        hour: Number(hour.value),
        model: model.value,
        budgetChars: Number(budget.value),
      });
      await refreshStatus();
    };
    form.append('Weekly on', day, 'at', hour, ':00 · model', model, '· budget (chars)', budget, save);
    sections.settings.appendChild(form);
  }

  async function refreshAll() {
    const st = await refreshStatus();
    renderSettings(st);
    await Promise.all([renderBriefing(st), renderLoops(), renderDecisionLog()]);
  }

  runBtn.onclick = async () => {
    const pending = api.ipc.invoke('run').catch((e) => ({ started: false, reason: e instanceof Error ? e.message : String(e) }));
    await refreshStatus();
    const r = await pending;
    if (r?.started === false) status.textContent = r.reason;
    await refreshStatus();
  };
  const off = api.ipc.on('run:finished', () => void refreshAll());

  // Briefing markdown is untrusted LLM/connector content (see the marked
  // html-renderer override above): links must never navigate the app window
  // in place. One delegated listener on the section (its innerHTML is
  // replaced wholesale by renderBriefing, but the <section> element itself
  // persists across refreshes) intercepts every anchor click; only
  // http(s) links are forwarded to the OS browser via openExternal, anything
  // else (relative hrefs, javascript:, etc.) is just suppressed.
  const onBriefingClick = (e) => {
    const a = e.target.closest?.('a');
    if (!a) return;
    e.preventDefault();
    const href = a.getAttribute('href') || '';
    if (href.startsWith('http://') || href.startsWith('https://')) {
      api.openExternal(href);
    }
  };
  sections.briefing.addEventListener('click', onBriefingClick);

  void refreshAll();

  return () => {
    off();
    sections.briefing.removeEventListener('click', onBriefingClick);
  };
}
