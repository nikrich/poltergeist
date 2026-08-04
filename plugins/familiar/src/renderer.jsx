// Familiar screen — React port of the approved Claude Design direction B
// (ghostbrain Design System project, ui_kits/plugin/familiar-*.jsx), mapped to
// the plugin's real data. Bundles the app's own components; their Tailwind
// classes resolve because the plugin renders inside the app page.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { marked } from 'marked';

import { Panel } from '../../../desktop/src/renderer/components/Panel';
import { Btn } from '../../../desktop/src/renderer/components/Btn';
import { Pill } from '../../../desktop/src/renderer/components/Pill';
import { Eyebrow } from '../../../desktop/src/renderer/components/Eyebrow';
import { Toggle } from '../../../desktop/src/renderer/components/Toggle';
import { SkeletonRows } from '../../../desktop/src/renderer/components/SkeletonRows';
import { PanelEmpty } from '../../../desktop/src/renderer/components/PanelEmpty';
import { PanelError } from '../../../desktop/src/renderer/components/PanelError';
import { Lucide } from '../../../desktop/src/renderer/components/Lucide';
import { TopBar } from '../../../desktop/src/renderer/components/TopBar';

import { parseOpenLoops, renderOpenLoops, parseDecisions } from './lib/trackers.js';
import { splitBriefingSections, ageDays, sectionIcon, historyFromRuns } from './lib/briefing.js';
import { scheduleFields, briefingSubtitle } from './lib/ui.js';

// LLM/connector-derived content is untrusted: markdown renders, raw HTML does not.
marked.use({ renderer: { html: () => '' } });

const LOOPS_PATH = 'Familiar/open-loops.md';
const DECISIONS_PATH = 'Familiar/decisions.md';

// ---------------------------------------------------------------- data access
async function readNote(api, path) {
  const r = await api.sidecar.request('GET', `/v1/notes?path=${encodeURIComponent(path)}`);
  if (r.ok) return r.data.body;
  if (r.status === 404) return null;
  throw new Error(r.error);
}

async function writeNote(api, path, content) {
  const r = await api.sidecar.request('PUT', '/v1/notes', { path, content });
  if (!r.ok) throw new Error(r.error);
}

function fmtWhen(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

// ---------------------------------------------------------------- primitives
const Divider = ({ my = 0 }) => <div style={{ height: 1, background: 'var(--hairline)', margin: `${my}px 0` }} />;

const SECTIONS = [
  { id: 'briefing', label: 'Briefing', icon: 'newspaper' },
  { id: 'loops', label: 'Open loops', icon: 'repeat' },
  { id: 'decisions', label: 'Decisions', icon: 'gavel' },
  { id: 'history', label: 'History', icon: 'history' },
  { id: 'settings', label: 'Settings', icon: 'settings' },
];

function SectionNav({ active, onChange }) {
  return (
    <div role="tablist" style={{ display: 'inline-flex', gap: 2, padding: 3, background: 'var(--bg-fog)', borderRadius: 8, border: '1px solid var(--hairline)' }}>
      {SECTIONS.map((s) => {
        const on = active === s.id;
        return (
          <button key={s.id} role="tab" aria-selected={on} onClick={() => onChange(s.id)}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 11px', borderRadius: 6, cursor: 'pointer',
              border: '1px solid ' + (on ? 'var(--hairline-2)' : 'transparent'),
              background: on ? 'var(--bg-vellum)' : 'transparent',
              color: on ? 'var(--ink-0)' : 'var(--ink-2)',
              fontFamily: 'var(--font-body)', fontSize: 13, fontWeight: on ? 600 : 500,
            }}>
            <Lucide name={s.icon} size={14} color={on ? 'var(--neon)' : 'currentColor'} />
            {s.label}
          </button>
        );
      })}
    </div>
  );
}

function RunStatusBar({ status, lastRun, onRun }) {
  const state = status?.running ? 'running'
    : !status?.lastSuccessfulRunAt && !lastRun ? 'never'
    : lastRun && !lastRun.ok ? 'failed'
    : 'idle';
  const cfg = {
    idle: { dot: 'var(--neon)', tone: 'moss', label: 'idle' },
    running: { dot: 'var(--neon)', tone: 'neon', label: 'running' },
    failed: { dot: 'var(--pill-oxblood-fg, #ff8a7c)', tone: 'oxblood', label: 'failed' },
    never: { dot: 'var(--ink-3)', tone: 'fog', label: 'never run' },
  }[state];

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 16, padding: '10px 16px', borderBottom: '1px solid var(--hairline)',
      background: state === 'running' ? 'linear-gradient(90deg, rgba(197,255,61,0.06), transparent 60%)'
        : state === 'failed' ? 'linear-gradient(90deg, rgba(255,138,124,0.06), transparent 60%)' : 'transparent',
    }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <span style={{
          width: 8, height: 8, borderRadius: '50%', background: cfg.dot,
          animation: state === 'running' ? 'fam-pulse 1.4s ease-in-out infinite' : 'none',
        }} />
        <Pill tone={cfg.tone}>{cfg.label}</Pill>
      </span>

      {state === 'running' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: 1, minWidth: 0 }}>
          <span style={{ fontSize: 13, color: 'var(--ink-1)', whiteSpace: 'nowrap' }}>reading the vault delta · synthesising…</span>
          <div style={{ flex: 1, height: 4, borderRadius: 2, background: 'var(--hairline)', overflow: 'hidden', maxWidth: 260 }}>
            <div style={{ width: '58%', height: '100%', background: 'var(--neon)', borderRadius: 2, animation: 'fam-indet 2.4s ease-in-out infinite' }} />
          </div>
        </div>
      )}
      {state === 'idle' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 20, flex: 1, minWidth: 0, fontSize: 13 }}>
          <span style={{ color: 'var(--ink-2)' }}>last run <span style={{ color: 'var(--ink-1)' }}>{fmtWhen(lastRun?.finishedAt ?? status?.lastSuccessfulRunAt)}</span></span>
          <span style={{ color: 'var(--ink-2)' }}>next <span style={{ color: 'var(--ink-1)' }}>{fmtWhen(status?.nextRunAt)}</span></span>
        </div>
      )}
      {state === 'failed' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0, fontSize: 13, overflow: 'hidden' }}>
          <span style={{ color: 'var(--ink-1)', flexShrink: 0 }}>last run failed —</span>
          <span style={{ color: 'var(--ink-2)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{lastRun?.error}</span>
        </div>
      )}
      {state === 'never' && (
        <div style={{ flex: 1, minWidth: 0, fontSize: 13, color: 'var(--ink-2)' }}>
          no briefing yet · scheduled {status?.config?.day} {String(status?.config?.hour).padStart(2, '0')}:00
        </div>
      )}

      <div style={{ flexShrink: 0 }}>
        {state === 'running'
          ? <Btn variant="secondary" size="sm" disabled icon={<Lucide name="loader" size={13} />}>running…</Btn>
          : <Btn variant="primary" size="sm" icon={<Lucide name={state === 'failed' ? 'rotate-cw' : 'play'} size={13} />} onClick={onRun}>
              {state === 'failed' ? 'retry' : state === 'never' ? 'run first briefing' : 'run now'}
            </Btn>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- briefing
function Markdown({ md, api }) {
  const html = useMemo(() => marked.parse(md ?? ''), [md]);
  const onClick = useCallback((e) => {
    const a = e.target.closest?.('a');
    if (!a) return;
    e.preventDefault();
    const href = a.getAttribute('href') ?? '';
    if (/^https?:\/\//.test(href)) api.openExternal(href);
  }, [api]);
  // Safe by construction: marked is configured above to drop raw HTML tokens,
  // so `html` only ever contains markup marked itself generated from text
  // (security-reviewed posture; the app CSP additionally blocks inline script).
  return <div className="fam-prose" onClick={onClick} dangerouslySetInnerHTML={{ __html: html }} />;
}

function BriefeSection({ icon, kicker, innerRef, children }) {
  return (
    <section ref={innerRef} style={{ scrollMarginTop: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{
          width: 24, height: 24, borderRadius: 6, flexShrink: 0, background: 'var(--neon-mist)',
          border: '1px solid var(--neon)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <Lucide name={icon} size={13} color="var(--neon)" />
        </span>
        <Eyebrow>{kicker}</Eyebrow>
      </div>
      {children}
    </section>
  );
}

function BriefingReader({ doc, api, sectionRefs }) {
  const { preamble, sections } = useMemo(() => splitBriefingSections(doc.body), [doc.body]);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      {preamble && <div style={{ fontSize: 13, color: 'var(--ink-2)', fontStyle: 'italic' }}><Markdown md={preamble} api={api} /></div>}
      {sections.map((s, i) => (
        <div key={s.title}>
          {i > 0 && <div style={{ marginBottom: 28 }}><Divider /></div>}
          <BriefeSection icon={sectionIcon(s.title)} kicker={s.title} innerRef={(el) => { sectionRefs.current[i] = el; }}>
            <Markdown md={s.body} api={api} />
          </BriefeSection>
        </div>
      ))}
      {!sections.length && <Markdown md={doc.body} api={api} />}
    </div>
  );
}

const RailStat = ({ n, label }) => (
  <div>
    <div style={{ fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: 30, lineHeight: 1, color: 'var(--ink-0)', letterSpacing: '-0.02em' }}>{n}</div>
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--ink-2)', marginTop: 4 }}>{label}</div>
  </div>
);

function MetaRail({ doc, run, loops, sections, onJumpSection, onOpenLoops }) {
  const open = loops.filter((l) => l.status === 'open');
  const stale = loops.filter((l) => l.status === 'stale');
  const oldest = [...open, ...stale]
    .map((l) => ({ ...l, age: ageDays(l.firstSeen) }))
    .filter((l) => l.age != null)
    .sort((a, b) => b.age - a.age)
    .slice(0, 3);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, position: 'sticky', top: 12 }}>
      <Panel title="this run" subtitle={doc.date ?? ''}>
        <div style={{ display: 'flex', gap: 22 }}>
          <RailStat n={open.length} label="open loops" />
          <RailStat n={stale.length} label="stale" />
          <RailStat n={run?.noteCount ?? '—'} label="notes read" />
        </div>
        <Divider my={14} />
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--ink-2)' }}>
          <span>generated {fmtWhen(run?.finishedAt)}</span>
          {run?.costUsd != null && <span style={{ fontFamily: 'var(--font-mono)' }}>${run.costUsd.toFixed(2)}</span>}
        </div>
      </Panel>

      {sections.length > 0 && (
        <Panel title="jump to">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {sections.map((s, i) => (
              <button key={s.title} onClick={() => onJumpSection(i)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 9, width: '100%', padding: '7px 8px', borderRadius: 6,
                  cursor: 'pointer', background: 'transparent', border: 'none', textAlign: 'left',
                  color: 'var(--ink-1)', fontFamily: 'var(--font-body)', fontSize: 13,
                }}>
                <Lucide name={sectionIcon(s.title)} size={13} color="var(--ink-2)" />
                {s.title}
              </button>
            ))}
          </div>
        </Panel>
      )}

      {oldest.length > 0 && (
        <Panel title="oldest loops" subtitle="AGING · NEEDS A NUDGE" action={<Btn variant="ghost" size="sm" onClick={onOpenLoops}>all →</Btn>}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {oldest.map((l) => (
              <div key={l.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: l.age > 10 ? 'var(--pill-oxblood-fg, #ff8a7c)' : 'var(--ink-2)', flexShrink: 0, marginTop: 1 }}>{l.age}d</span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, color: 'var(--ink-0)', lineHeight: 1.35 }}>{l.text}</div>
                  {l.owedTo && <div style={{ fontSize: 11.5, color: 'var(--ink-2)', marginTop: 2 }}>owed to {l.owedTo}</div>}
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- open loops
const ghostIconBtn = {
  width: 26, height: 26, borderRadius: 6, flexShrink: 0, cursor: 'pointer',
  border: '1px solid transparent', background: 'transparent', color: 'var(--ink-2)',
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 0,
};

function LoopsList({ loops, onSetStatus }) {
  const [filter, setFilter] = useState('all');
  const active = loops.filter((l) => l.status !== 'dismissed');
  const counts = {
    all: active.filter((l) => l.status !== 'done').length,
    owed: active.filter((l) => l.status !== 'done' && l.owedTo).length,
    stale: active.filter((l) => l.status === 'stale').length,
  };
  const filters = [
    { id: 'all', label: 'All' },
    { id: 'owed', label: 'Owed to someone' },
    { id: 'stale', label: 'Stale' },
  ];
  const visible = active.filter((l) =>
    filter === 'owed' ? Boolean(l.owedTo) : filter === 'stale' ? l.status === 'stale' : true);

  return (
    <Panel title="open loops" subtitle={`${counts.all} OPEN · ${counts.stale} STALE`}>
      <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
        {filters.map((f) => {
          const on = filter === f.id;
          return (
            <button key={f.id} onClick={() => setFilter(f.id)}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 10px', borderRadius: 6, cursor: 'pointer',
                border: '1px solid ' + (on ? 'var(--neon)' : 'var(--hairline-2)'),
                background: on ? 'var(--neon-mist)' : 'transparent',
                color: on ? 'var(--neon-ink)' : 'var(--ink-2)',
                fontFamily: 'var(--font-body)', fontSize: 12.5, fontWeight: on ? 600 : 500,
              }}>
              {f.label}
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.8 }}>{counts[f.id]}</span>
            </button>
          );
        })}
      </div>

      {visible.length === 0 && <PanelEmpty icon="repeat" message="Nothing here — loops appear after a sweep, and this filter has none." />}

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {visible.map((l, i) => {
          const done = l.status === 'done';
          const age = ageDays(l.firstSeen);
          return (
            <div key={l.id} style={{
              display: 'flex', alignItems: 'center', gap: 12, padding: '11px 4px',
              borderTop: i === 0 ? 'none' : '1px solid var(--hairline)',
              opacity: done ? 0.45 : 1,
            }}>
              <button aria-label="check off" onClick={() => onSetStatus(l.id, done ? 'open' : 'done')}
                style={{
                  width: 18, height: 18, borderRadius: 5, flexShrink: 0, cursor: 'pointer',
                  border: '1px solid ' + (done ? 'var(--neon)' : 'var(--hairline-3)'),
                  background: done ? 'var(--neon)' : 'transparent',
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 0,
                }}>
                {done && <Lucide name="check" size={12} color="#0E0F12" />}
              </button>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, color: done ? 'var(--ink-2)' : 'var(--ink-0)', lineHeight: 1.35, textDecoration: done ? 'line-through' : 'none' }}>
                  {l.text}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 4, fontSize: 12, color: 'var(--ink-2)' }}>
                  {l.owedTo && (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                      <Lucide name="arrow-up-right" size={12} />
                      owed to <span style={{ color: 'var(--ink-1)' }}>{l.owedTo}</span>
                    </span>
                  )}
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }} title={l.sourcePath}>
                    <Lucide name="file-text" size={12} />
                    {String(l.sourcePath ?? '').split('/').pop()}
                  </span>
                  {l.status === 'stale' && <Pill tone="oxblood">stale</Pill>}
                </div>
              </div>

              {age != null && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, flexShrink: 0, color: age > 10 ? 'var(--pill-oxblood-fg, #ff8a7c)' : 'var(--ink-2)' }}>{age}d</span>
              )}
              <button aria-label="dismiss" title="dismiss" onClick={() => onSetStatus(l.id, 'dismissed')} style={ghostIconBtn}>
                <Lucide name="x" size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------- decisions
function DecisionsLog({ decisions }) {
  if (!decisions.length) {
    return <Panel title="decisions"><PanelEmpty icon="gavel" message="No decisions logged yet — Familiar records the ones it detects so they stop getting re-litigated." /></Panel>;
  }
  const rows = [...decisions].reverse();
  return (
    <Panel title="decisions" subtitle="NEWEST FIRST">
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {rows.map((d, i) => (
          <div key={`${d.date}-${i}`} style={{ display: 'flex', gap: 16, padding: '14px 0', borderTop: i === 0 ? 'none' : '1px solid var(--hairline)' }}>
            <div style={{ width: 84, flexShrink: 0, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink-2)', paddingTop: 1 }}>{d.date}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14.5, fontWeight: 600, color: 'var(--ink-0)', letterSpacing: '-0.01em' }}>{d.text}</div>
              <div style={{ fontSize: 12, color: 'var(--ink-2)', marginTop: 3, display: 'inline-flex', alignItems: 'center', gap: 5 }} title={d.sourcePath}>
                <Lucide name="file-text" size={12} />
                {String(d.sourcePath ?? '').split('/').pop()}
              </div>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------- history
function HistoryList({ history, currentPath, onOpen }) {
  if (!history.length) {
    return <Panel title="briefing history"><PanelEmpty icon="history" message="No past briefings yet — this fills in every week." /></Panel>;
  }
  return (
    <Panel title="briefing history" subtitle="TAP TO RE-OPEN">
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {history.map((h, i) => {
          const current = h.path === currentPath;
          return (
            <button key={h.path} onClick={() => onOpen(h)}
              style={{
                display: 'flex', alignItems: 'center', gap: 14, textAlign: 'left', width: '100%', padding: '13px 8px', cursor: 'pointer',
                borderTop: i === 0 ? 'none' : '1px solid var(--hairline)',
                borderLeft: current ? '2px solid var(--neon)' : '2px solid transparent',
                background: current ? 'var(--neon-mist)' : 'transparent',
                border: 'none', borderRadius: current ? 4 : 0,
              }}>
              <Lucide name="newspaper" size={16} color={current ? 'var(--neon)' : 'var(--ink-3)'} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--ink-0)' }}>{h.date}</span>
                  {i === 0 && <Pill tone="neon">latest</Pill>}
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--ink-2)', marginTop: 3 }}>
                  {h.noteCount != null ? `${h.noteCount} notes` : ''}{h.costUsd != null ? ` · $${h.costUsd.toFixed(2)}` : ''}
                </div>
              </div>
              <Lucide name="chevron-right" size={16} color="var(--ink-3)" />
            </button>
          );
        })}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------- settings
const selStyle = {
  fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--ink-0)', background: 'var(--bg-fog)',
  border: '1px solid var(--hairline-2)', borderRadius: 7, padding: '7px 10px', minWidth: 130, cursor: 'pointer',
};

function Field({ label, hint, children }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 20, padding: '14px 0', borderTop: '1px solid var(--hairline)' }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 14, color: 'var(--ink-0)', fontWeight: 500 }}>{label}</div>
        {hint && <div style={{ fontSize: 12.5, color: 'var(--ink-2)', marginTop: 2 }}>{hint}</div>}
      </div>
      <div style={{ flexShrink: 0 }}>{children}</div>
    </div>
  );
}

function SettingsForm({ config, onSave }) {
  const [cadence, setCadence] = useState(config.cadence);
  const [day, setDay] = useState(config.day);
  const [hour, setHour] = useState(config.hour);
  const [model, setModel] = useState(config.model);
  const [budget, setBudget] = useState(config.budgetChars);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState(null);

  const { showDay } = scheduleFields(cadence);

  const save = async () => {
    setErr(null);
    try {
      await onSave({ cadence, day, hour: Number(hour), model, budgetChars: Number(budget) });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Panel title="schedule" subtitle="WHEN FAMILIAR RUNS">
        <div style={{ marginTop: -14 }}>
          <Field label="Cadence" hint="How often the briefing runs">
            <select value={cadence} onChange={(e) => setCadence(e.target.value)} style={selStyle}>
              {['weekly', 'daily'].map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </Field>
          {showDay && (
            <Field label="Day" hint="Which day the briefing lands">
              <select value={day} onChange={(e) => setDay(e.target.value)} style={selStyle}>
                {['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'].map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </Field>
          )}
          <Field label="Hour" hint="Local time, 24-hour">
            <select value={hour} onChange={(e) => setHour(e.target.value)} style={selStyle}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>)}
            </select>
          </Field>
        </div>
      </Panel>

      <Panel title="model & budget" subtitle="HOW THE SWEEP READS YOUR WEEK">
        <div style={{ marginTop: -14 }}>
          <Field label="Model" hint="Bigger models reason across more sources">
            <select value={model} onChange={(e) => setModel(e.target.value)} style={selStyle}>
              {['haiku', 'sonnet', 'opus'].map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </Field>
          <div style={{ padding: '14px 0 2px', borderTop: '1px solid var(--hairline)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 14, color: 'var(--ink-0)', fontWeight: 500 }}>Character budget</div>
                <div style={{ fontSize: 12.5, color: 'var(--ink-2)', marginTop: 2 }}>How much of the week's notes one sweep reads</div>
              </div>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, color: 'var(--neon-ink)' }}>{Math.round(budget / 1000)}k</span>
            </div>
            <input type="range" min="50000" max="500000" step="10000" value={budget}
              onChange={(e) => setBudget(Number(e.target.value))} style={{ width: '100%', accentColor: 'var(--neon)' }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-3)', marginTop: 4 }}>
              <span>50k · quick</span><span>500k · thorough</span>
            </div>
          </div>
        </div>
      </Panel>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Btn variant="primary" size="sm" onClick={save}>save settings</Btn>
        {saved && <Pill tone="moss">saved</Pill>}
        {err && <span style={{ fontSize: 12.5, color: 'var(--pill-oxblood-fg, #ff8a7c)' }}>{err}</span>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- app
function App({ api }) {
  const [section, setSection] = useState('briefing');
  const [status, setStatus] = useState(null);
  const [doc, setDoc] = useState(null); // {path, date, body} | null
  const [loops, setLoops] = useState([]);
  const [decisions, setDecisions] = useState([]);
  const [loadErr, setLoadErr] = useState(null);
  const sectionRefs = useRef([]);

  const history = useMemo(() => historyFromRuns(status?.lastRuns), [status]);
  const lastRun = status?.lastRuns?.[status.lastRuns.length - 1] ?? null;
  const currentRun = useMemo(
    () => history.find((h) => h.path === doc?.path) ?? null,
    [history, doc],
  );

  const refreshStatus = useCallback(async () => {
    const st = await api.ipc.invoke('status');
    setStatus(st);
    return st;
  }, [api]);

  const loadTrackers = useCallback(async () => {
    const [loopsMd, decisionsMd] = await Promise.all([readNote(api, LOOPS_PATH), readNote(api, DECISIONS_PATH)]);
    setLoops(parseOpenLoops(loopsMd ?? '').loops);
    setDecisions(parseDecisions(decisionsMd ?? ''));
  }, [api]);

  const loadBriefing = useCallback(async (path) => {
    if (!path) { setDoc(null); return; }
    const body = await readNote(api, path);
    setDoc(body == null ? null : { path, date: /(\d{4}-\d{2}-\d{2})/.exec(path)?.[1] ?? '', body });
  }, [api]);

  const refreshAll = useCallback(async () => {
    setLoadErr(null);
    try {
      const st = await refreshStatus();
      const hist = historyFromRuns(st?.lastRuns);
      await Promise.all([loadBriefing(hist[0]?.path), loadTrackers()]);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    }
  }, [refreshStatus, loadBriefing, loadTrackers]);

  useEffect(() => {
    void refreshAll();
    const off = api.ipc.on('run:finished', () => void refreshAll());
    return () => off();
  }, [api, refreshAll]);

  const run = async () => {
    const pending = api.ipc.invoke('run').catch((e) => ({ started: false, reason: e instanceof Error ? e.message : String(e) }));
    await refreshStatus();
    const r = await pending;
    if (r?.started === false && r.reason) setLoadErr(r.reason);
    await refreshStatus();
  };

  // Fresh-read → modify by id → regenerate → PUT: user edits always win and a
  // concurrent sweep's additions survive.
  const setLoopStatus = async (id, next) => {
    try {
      const fresh = parseOpenLoops((await readNote(api, LOOPS_PATH)) ?? '');
      const updated = fresh.loops.map((l) => (l.id === id ? { ...l, status: next } : l));
      await writeNote(api, LOOPS_PATH, renderOpenLoops(updated, fresh.unparsed));
      setLoops(updated);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    }
  };

  const saveConfig = async (partial) => {
    await api.ipc.invoke('config:set', partial);
    await refreshStatus();
  };

  const jumpSection = (i) => sectionRefs.current[i]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const briefingSections = useMemo(() => (doc ? splitBriefingSections(doc.body).sections : []), [doc]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100%', background: 'var(--bg-paper)' }}>
      <TopBar title="Familiar" subtitle={briefingSubtitle(status?.config?.cadence)} right={<SectionNav active={section} onChange={setSection} />} />
      <RunStatusBar status={status} lastRun={lastRun} onRun={run} />

      <div style={{ padding: 20, maxWidth: 1120, width: '100%', margin: '0 auto' }}>
        {loadErr && (
          <div style={{ marginBottom: 14 }}>
            <PanelError message={loadErr} onRetry={() => void refreshAll()} />
          </div>
        )}

        {section === 'briefing' && (
          status?.running && !doc ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1.7fr 1fr', gap: 20 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
                {['Themes', 'Open loops', 'Decisions'].map((k) => (
                  <div key={k}>
                    <div style={{ marginBottom: 12 }}><Eyebrow>{k}</Eyebrow></div>
                    <SkeletonRows count={3} height={22} />
                  </div>
                ))}
              </div>
              <Panel title="this run"><SkeletonRows count={4} height={20} /></Panel>
            </div>
          ) : doc ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1.7fr 1fr', gap: 24, alignItems: 'start' }}>
              <BriefingReader doc={doc} api={api} sectionRefs={sectionRefs} />
              <MetaRail doc={doc} run={currentRun} loops={loops} sections={briefingSections}
                onJumpSection={jumpSection} onOpenLoops={() => setSection('loops')} />
            </div>
          ) : (
            <Panel title="briefing" subtitle="NOTHING GENERATED YET">
              <PanelEmpty icon="newspaper"
                message="No briefing yet. Familiar assembles your first one from the last 7 days of vault activity."
                cta={{ label: 'Run first briefing', onClick: run }} />
            </Panel>
          )
        )}

        {section === 'loops' && <LoopsList loops={loops} onSetStatus={setLoopStatus} />}
        {section === 'decisions' && <DecisionsLog decisions={decisions} />}
        {section === 'history' && <HistoryList history={history} currentPath={doc?.path} onOpen={(h) => { void loadBriefing(h.path); setSection('briefing'); }} />}
        {section === 'settings' && status?.config && <SettingsForm config={status.config} onSave={saveConfig} />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- mount
const CSS = `
@keyframes fam-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(197,255,61,0.5); } 50% { box-shadow: 0 0 0 5px rgba(197,255,61,0); } }
@keyframes fam-indet { 0% { transform: translateX(-100%); } 100% { transform: translateX(260%); } }
.fam-prose { font-size: 14px; line-height: 1.6; color: var(--ink-1); }
.fam-prose h1, .fam-prose h2, .fam-prose h3 { color: var(--ink-0); letter-spacing: -0.01em; margin: 0 0 8px; font-size: 15px; }
.fam-prose p { margin: 0 0 10px; }
.fam-prose ul { margin: 0 0 10px; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; }
.fam-prose li::marker { color: var(--ink-3); }
.fam-prose strong { color: var(--ink-0); }
.fam-prose a { color: var(--neon-ink); text-decoration: none; border-bottom: 1px solid var(--neon-mist); }
.fam-prose code { font-family: var(--font-mono); font-size: 12.5px; background: var(--bg-fog); padding: 1px 5px; border-radius: 4px; }
`;

export function mount(el, api) {
  const style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);
  const root = createRoot(el);
  root.render(<App api={api} />);
  return () => {
    root.unmount();
    style.remove();
  };
}
