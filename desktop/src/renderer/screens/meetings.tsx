import { useCallback, useEffect, useMemo, useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { Eyebrow } from '../components/Eyebrow';
import { Panel } from '../components/Panel';
import { Ghost } from '../components/Ghost';
import { useMeeting } from '../stores/meeting';
import { useNavigation } from '../stores/navigation';
import { useNoteView } from '../stores/note-view';
import { stub } from '../stores/toast';
import { useAgenda, useMeetings } from '../lib/api/hooks';
import type { AgendaItem, PastMeeting } from '../../shared/api-types';
import { SkeletonRows } from '../components/SkeletonRows';
import { PanelEmpty } from '../components/PanelEmpty';
import { PanelError } from '../components/PanelError';
import { mmss } from '../lib/format';

function parseAgendaTime(item: AgendaItem): Date | null {
  // item.time is HH:MM in the user's local timezone; combine with today.
  const match = item.time.match(/^(\d{2}):(\d{2})$/);
  if (!match) return null;
  const d = new Date();
  d.setHours(Number(match[1]), Number(match[2]), 0, 0);
  return d;
}

function parseDurationMinutes(dur: string): number {
  // Repo emits "30m", "1h", "1h15m", "1h05m", etc.
  let total = 0;
  const h = dur.match(/(\d+)h/);
  const m = dur.match(/(\d+)m/);
  if (h) total += Number(h[1]) * 60;
  if (m) total += Number(m[1]);
  return total;
}

function relativeMinutes(target: Date | null): string {
  if (target === null) return '';
  const diffMs = target.getTime() - Date.now();
  const diffMin = Math.round(diffMs / 60000);
  if (diffMin <= -60) return `started ${Math.round(-diffMin / 60)}h ago`;
  if (diffMin < -1) return `started ${-diffMin}m ago`;
  if (diffMin < 1) return 'starting now';
  if (diffMin < 60) return `starts in ${diffMin}m`;
  return `starts in ${Math.round(diffMin / 60)}h`;
}

export function MeetingsScreen() {
  const {
    phase,
    startedAt,
    title: activeTitle,
    transcriptPath,
    error: activeError,
    start,
    stop,
    reset,
  } = useMeeting();
  const agenda = useAgenda();
  const meetings = useMeetings({ limit: 1 });

  const upcoming = useMemo<AgendaItem | null>(() => {
    if (!agenda.data) return null;
    const now = Date.now();
    const candidates = agenda.data
      .filter((e) => e.status === 'upcoming')
      .map((e) => ({ item: e, start: parseAgendaTime(e) }))
      .filter((x): x is { item: AgendaItem; start: Date } => x.start !== null);
    candidates.sort((a, b) => a.start.getTime() - b.start.getTime());
    const ongoing = candidates.find(
      ({ item, start }) =>
        start.getTime() <= now &&
        start.getTime() + parseDurationMinutes(item.duration) * 60_000 > now,
    );
    if (ongoing) return ongoing.item;
    const future = candidates.find(({ start }) => start.getTime() > now);
    return future?.item ?? null;
  }, [agenda.data]);

  const subtitle = (() => {
    if (phase === 'recording') return '· recording in progress';
    if (phase === 'transcribing') return '· transcribing';
    if (meetings.data) return `${meetings.data.total} in vault`;
    return '…';
  })();

  const handleStartForEvent = useCallback(
    () => start(upcoming ? { title: upcoming.title } : {}),
    [start, upcoming],
  );
  const handleStartManual = useCallback(() => start({}), [start]);

  return (
    <div className="flex-1 overflow-y-auto bg-paper">
      <TopBar
        title="meetings"
        subtitle={subtitle}
        right={
          <div className="flex gap-2">
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="settings-2" size={13} />}
              onClick={() => stub(4)}
            >
              audio
            </Btn>
            <Btn
              variant="secondary"
              size="sm"
              icon={<Lucide name="upload" size={13} />}
              onClick={() => stub(4)}
            >
              import recording
            </Btn>
          </div>
        }
      />

      {phase === 'pre' &&
        (upcoming ? (
          <PreMeeting onStart={handleStartForEvent} event={upcoming} />
        ) : (
          <IdleLobby onStart={handleStartManual} />
        ))}
      {phase === 'recording' && startedAt !== null && (
        <ActiveRecording
          startedAt={startedAt}
          title={activeTitle}
          onStop={stop}
        />
      )}
      {phase === 'transcribing' && (
        <Transcribing title={activeTitle} startedAt={startedAt} />
      )}
      {phase === 'post' && (
        <PostMeeting
          title={activeTitle}
          transcriptPath={transcriptPath}
          error={activeError}
          onClose={reset}
        />
      )}

      <MeetingHistory />
    </div>
  );
}

// ── Pre-meeting (lobby) ────────────────────────────────────────────────────
interface PreMeetingProps {
  onStart: () => void;
  event: AgendaItem;
}

function PreMeeting({ onStart, event }: PreMeetingProps) {
  const setActive = useNavigation((s) => s.setActive);
  const startAt = parseAgendaTime(event);
  const rel = relativeMinutes(startAt);
  const endLabel = startAt
    ? new Date(
        startAt.getTime() + parseDurationMinutes(event.duration) * 60_000,
      ).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';
  return (
    <div className="mx-auto max-w-[1100px] px-8 py-6">
      <div className="gb-noise relative grid grid-cols-[1.3fr_1fr] gap-8 overflow-hidden rounded-lg border border-hairline bg-vellum p-8">
        <div
          className="pointer-events-none absolute -right-[100px] -top-[100px] h-[400px] w-[400px]"
          style={{
            background: 'radial-gradient(circle, rgba(197,255,61,0.08) 0%, transparent 60%)',
          }}
        />

        <div className="relative">
          <Pill tone="neon" className="mb-[14px]">
            <Lucide name="clock" size={9} /> {rel || 'today'}
          </Pill>
          <h2 className="m-0 font-display text-32 font-semibold leading-[1.05] tracking-tighter text-ink-0">
            {event.title}
          </h2>
          <div className="mt-3 flex items-center gap-4 font-mono text-11 text-ink-2">
            <span>
              <Lucide
                name="calendar"
                size={11}
                className="mr-[5px] align-[-2px] inline-block"
              />{' '}
              today · {event.time}
              {endLabel ? ` — ${endLabel}` : ''}
            </span>
            {event.duration && <span>{event.duration}</span>}
          </div>

          <div className="mt-6 rounded-md border border-hairline bg-paper p-4">
            <Eyebrow className="mb-2">poltergeist primed</Eyebrow>
            <ul className="m-0 flex list-none flex-col gap-[6px] p-0">
              <li className="flex items-start gap-2 text-12 text-ink-1">
                <Lucide name="check" size={11} color="var(--neon)" className="mt-1" />
                <span>
                  transcript will land in{' '}
                  <span className="font-mono text-11">
                    20-contexts/&lt;ctx&gt;/calendar/transcripts/
                  </span>
                </span>
              </li>
              <li className="flex items-start gap-2 text-12 text-ink-1">
                <Lucide name="check" size={11} color="var(--neon)" className="mt-1" />
                <span>
                  auto-record skips Focus blocks; manual start works for any
                  session
                </span>
              </li>
            </ul>
          </div>

          <div className="mt-6 flex gap-[10px]">
            <Btn
              variant="record"
              size="lg"
              // intentional fixed color: dark dot sits inside the always-bright oxblood record button
              icon={<span className="h-2 w-2 rounded-full bg-[#0E0F12]" />}
              onClick={onStart}
            >
              start recording
            </Btn>
            <Btn
              variant="ghost"
              size="lg"
              icon={<Lucide name="settings-2" size={14} />}
              onClick={() => setActive('settings')}
            >
              configure…
            </Btn>
          </div>
        </div>

        {/* Right: participants + audio preview */}
        <div className="relative flex flex-col gap-4">
          <Eyebrow>participants · {event.with.length || '—'}</Eyebrow>
          <div className="flex flex-col gap-1">
            {event.with.length > 0 ? (
              event.with.map((name) => <AttendeeRow key={name} name={name} />)
            ) : (
              <div className="rounded-sm px-2 py-[6px] text-12 text-ink-3">
                no attendees on the invite
              </div>
            )}
          </div>

          <div className="mt-2">
            <Eyebrow className="mb-2">audio source</Eyebrow>
            <AudioSource icon="mic" label="MacBook Pro Microphone" sub="default · 48 kHz" active />
            <AudioSource
              icon="volume-2"
              label="System audio (loopback)"
              sub="capture both sides of meet"
              active
            />
          </div>

          <div className="mt-2">
            <Eyebrow className="mb-2">level</Eyebrow>
            <Waveform />
          </div>
        </div>
      </div>
    </div>
  );
}

function IdleLobby({ onStart }: { onStart: () => void }) {
  return (
    <div className="mx-auto max-w-[1100px] px-8 py-6">
      <div className="flex flex-col items-center gap-[18px] rounded-lg border border-hairline bg-vellum p-12">
        <Ghost size={56} floating />
        <h2 className="m-0 font-display text-24 font-semibold tracking-tight-x text-ink-0">
          no upcoming meetings.
        </h2>
        <p className="m-0 max-w-[420px] text-center text-13 leading-[1.55] text-ink-2">
          your calendar is clear. start a manual recording if you want to capture
          a working session — it&rsquo;ll transcribe and file itself when you
          stop.
        </p>
        <Btn
          variant="record"
          size="lg"
          icon={<span className="h-2 w-2 rounded-full bg-[#0E0F12]" />}
          onClick={onStart}
        >
          start recording
        </Btn>
      </div>
    </div>
  );
}

function AttendeeRow({ name }: { name: string }) {
  const initial = name[0]?.toUpperCase() ?? '?';
  return (
    <div className="flex items-center gap-[10px] rounded-sm px-2 py-[6px]">
      <div
        className="flex h-6 w-6 items-center justify-center rounded-full text-11 font-semibold text-[#0E0F12]"
        style={{ background: 'var(--neon)' }}
      >
        {initial}
      </div>
      <span className="flex-1 text-12 text-ink-0">{name}</span>
    </div>
  );
}

interface AudioSourceProps {
  icon: string;
  label: string;
  sub: string;
  active: boolean;
}

function AudioSource({ icon, label, sub, active }: AudioSourceProps) {
  // Read-only — devices are auto-detected by the recorder (BlackHole + mic
  // from avfoundation). Source picker is out of scope for now; this strip
  // shows what *will* be captured.
  return (
    <div
      className={`mb-1 flex items-center gap-[10px] rounded-r6 border px-[10px] py-2 ${
        active
          ? 'border-neon/20 bg-neon/[0.08] opacity-100'
          : 'border-hairline bg-transparent opacity-55'
      }`}
      title="auto-detected by the recorder"
    >
      <Lucide name={icon} size={13} color={active ? 'var(--neon)' : 'var(--ink-2)'} />
      <div className="flex-1 leading-[1.2]">
        <div className="text-12 text-ink-0">{label}</div>
        <div className="font-mono text-9 text-ink-2">{sub}</div>
      </div>
      {active && <Lucide name="check" size={12} color="var(--neon)" />}
    </div>
  );
}

interface WaveformProps {
  live?: boolean;
}

function Waveform({ live = false }: WaveformProps) {
  const bars = 48;
  const heights = useMemo(() => Array.from({ length: bars }, () => 0.2 + Math.random() * 0.8), []);
  return (
    <div className="flex h-9 items-center gap-[2px] rounded-r6 border border-hairline bg-paper px-3">
      {heights.map((h, i) => (
        <div
          key={i}
          className={`flex-1 rounded-[1px] ${live ? 'bg-neon' : 'bg-ink-3'}`}
          style={{
            height: `${h * 100}%`,
            opacity: live ? 0.5 + h * 0.5 : 0.4 + h * 0.4,
            animation: live ? `gb-wave 1.${i % 9}s ease-in-out infinite alternate` : 'none',
          }}
        />
      ))}
    </div>
  );
}

// ── Active recording ───────────────────────────────────────────────────────
interface ActiveRecordingProps {
  startedAt: number;
  title: string | null;
  onStop: () => Promise<void> | void;
}

function ActiveRecording({ startedAt, title, onStop }: ActiveRecordingProps) {
  const [elapsed, setElapsed] = useState(0);
  const [stopping, setStopping] = useState(false);
  useEffect(() => {
    const tick = () => setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [startedAt]);

  const handleStop = async () => {
    if (stopping) return;
    setStopping(true);
    try {
      await onStop();
    } finally {
      setStopping(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1100px] px-8 py-6">
      <div
        className="mb-4 grid grid-cols-[auto_1fr_auto] items-center gap-6 rounded-lg border border-oxblood/30 p-5"
        style={{
          background:
            'linear-gradient(90deg, rgba(255,107,90,0.18) 0%, rgba(255,107,90,0.04) 100%)',
        }}
      >
        <div className="flex items-center gap-[10px]">
          <span
            className="h-3 w-3 rounded-full bg-oxblood"
            style={{
              boxShadow: '0 0 0 0 rgba(255,107,90,0.6)',
              animation: 'gb-pulse 1.4s ease-out infinite',
            }}
          />
          <div className="leading-[1.15]">
            <div className="font-mono text-10 uppercase tracking-eyebrow-loose text-oxblood">
              recording · live
            </div>
            <div className="font-display text-22 font-semibold tracking-tight-xx text-ink-0">
              {title || 'manual recording'}
            </div>
          </div>
        </div>

        <div className="flex justify-center">
          <div className="w-[280px]">
            <Waveform live />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="font-mono text-28 font-medium tracking-[0.04em] tabular-nums text-ink-0">
            {mmss(elapsed)}
          </div>
          <Btn
            variant="record"
            size="md"
            icon={<span className="h-[9px] w-[9px] bg-[#0E0F12]" />}
            onClick={handleStop}
            disabled={stopping}
          >
            {stopping ? 'stopping…' : 'stop'}
          </Btn>
        </div>
      </div>

      <div className="rounded-lg border border-hairline bg-vellum p-6">
        <Eyebrow className="mb-2">capturing audio</Eyebrow>
        <p className="m-0 max-w-[60ch] text-14 leading-[1.55] text-ink-1">
          poltergeist is recording your mic + system audio. transcription runs
          locally with whisper.cpp after you hit stop — no audio leaves your
          machine. the transcript will land under{' '}
          <span className="font-mono text-12">20-contexts/&lt;ctx&gt;/calendar/transcripts/</span>.
        </p>
      </div>
    </div>
  );
}

interface TranscribingProps {
  title: string | null;
  startedAt: number | null;
}

function Transcribing({ title, startedAt }: TranscribingProps) {
  const recordedSeconds =
    startedAt !== null ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000)) : null;
  return (
    <div className="mx-auto max-w-[1100px] px-8 py-6">
      <div className="flex items-center gap-5 rounded-lg border border-hairline bg-vellum p-6">
        <div
          className="h-4 w-4 rounded-full border-2 border-neon border-t-transparent"
          style={{ animation: 'gb-spin 0.9s linear infinite' }}
        />
        <div className="leading-[1.2]">
          <div className="font-mono text-10 uppercase tracking-eyebrow-loose text-neon-ink">
            transcribing
          </div>
          <div className="font-display text-20 font-semibold tracking-tight-x text-ink-0">
            {title || 'manual recording'}
          </div>
          <div className="mt-1 font-mono text-11 text-ink-2">
            running whisper.cpp locally
            {recordedSeconds !== null ? ` · ${mmss(recordedSeconds)} of audio` : ''}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Post-meeting summary ──────────────────────────────────────────────────
interface PostMeetingProps {
  title: string | null;
  transcriptPath: string | null;
  error: string | null;
  onClose: () => Promise<void> | void;
}

function PostMeeting({ title, transcriptPath, error, onClose }: PostMeetingProps) {
  const openNote = useNoteView((s) => s.open);
  return (
    <div className="mx-auto max-w-[1100px] px-8 py-6">
      <div className="mb-4 rounded-lg border border-hairline bg-vellum p-7">
        <div className="mb-4 flex items-center gap-3">
          {error ? (
            <Pill tone="oxblood">
              <Lucide name="alert-triangle" size={9} /> error
            </Pill>
          ) : (
            <Pill tone="moss">
              <Lucide name="check" size={9} /> saved
            </Pill>
          )}
          <Pill tone="fog">just now</Pill>
          <div className="flex-1" />
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="x" size={13} />}
            onClick={onClose}
            ariaLabel="close"
          />
        </div>

        <h2 className="m-0 font-display text-28 font-semibold tracking-tighter text-ink-0">
          {title || 'manual recording'}
        </h2>
        {transcriptPath && (
          <div className="mt-1 font-mono text-11 text-ink-2">{transcriptPath}</div>
        )}
        {error && (
          <p className="mt-3 text-13 leading-[1.5] text-oxblood">{error}</p>
        )}

        <div className="mt-5 flex gap-2">
          {transcriptPath && (
            <Btn
              variant="primary"
              size="sm"
              icon={<Lucide name="file-text" size={13} color="#0E0F12" />}
              onClick={() => openNote(transcriptPath)}
            >
              open transcript
            </Btn>
          )}
          <Btn variant="ghost" size="sm" onClick={onClose}>
            done
          </Btn>
        </div>
      </div>
    </div>
  );
}

interface ActionProps {
  who: string;
  text: string;
}

function _Action({ who, text }: ActionProps) {
  return (
    <div className="flex items-start gap-2 py-[6px]">
      <input
        type="checkbox"
        disabled
        className="mt-[3px] h-3 w-3 flex-shrink-0 cursor-not-allowed appearance-none rounded-sm border-[1.5px] border-ink-3 bg-transparent"
      />
      <div className="flex-1 text-12 leading-[1.5] text-ink-0">
        {text} <span className="font-mono text-10 text-neon-ink">@{who}</span>
      </div>
    </div>
  );
}

interface SmallStatProps {
  label: string;
  value: string;
}

function _SmallStat({ label, value }: SmallStatProps) {
  return (
    <div className="rounded-r6 border border-hairline bg-paper p-3">
      <Eyebrow>{label}</Eyebrow>
      <div className="mt-1 font-display text-22 font-semibold tracking-tight-xx text-ink-0">
        {value}
      </div>
    </div>
  );
}

// ── History ────────────────────────────────────────────────────────────────
function MeetingHistory() {
  const meetings = useMeetings({ limit: 50 });
  const openNote = useNoteView((s) => s.open);
  return (
    <div className="mx-auto max-w-[1100px] px-8 pb-10 pt-2">
      <Panel
        title="past meetings"
        subtitle={meetings.data ? `${meetings.data.total} in vault` : '…'}
        action={
          <Btn
            variant="ghost"
            size="sm"
            iconRight={<Lucide name="arrow-right" size={12} />}
            onClick={() => stub(3)}
          >
            vault
          </Btn>
        }
      >
        {meetings.isLoading && <SkeletonRows count={5} />}
        {meetings.isError && (
          <PanelError
            message={
              meetings.error instanceof Error ? meetings.error.message : 'failed to load meetings'
            }
            onRetry={() => meetings.refetch()}
          />
        )}
        {meetings.data && meetings.data.items.length === 0 && (
          <PanelEmpty icon="mic" message="no recorded meetings yet" />
        )}
        {meetings.data && meetings.data.items.length > 0 && (
          <>
            <div
              className="grid gap-3 border-b border-hairline px-2 pb-2 pt-1"
              style={{ gridTemplateColumns: '120px minmax(0, 1fr) 80px 80px minmax(0, 1fr)' }}
            >
              <Eyebrow>date</Eyebrow>
              <Eyebrow>title</Eyebrow>
              <Eyebrow>length</Eyebrow>
              <Eyebrow>speakers</Eyebrow>
              <Eyebrow>tags</Eyebrow>
            </div>
            {meetings.data.items.map((m) => (
              <HistoryRow
                key={m.id}
                m={m}
                onOpen={() => m.path && openNote(m.path)}
              />
            ))}
          </>
        )}
      </Panel>
    </div>
  );
}

interface HistoryRowProps {
  m: PastMeeting;
  onOpen: () => void;
}

function HistoryRow({ m, onOpen }: HistoryRowProps) {
  const className =
    'grid w-full items-center gap-3 rounded-sm bg-transparent px-2 py-[10px] text-left' +
    (m.path ? ' cursor-pointer hover:bg-paper' : ' opacity-70');
  const content = (
    <>
      <span className="font-mono text-11 text-ink-2">{m.date}</span>
      <span className="text-13 text-ink-0">{m.title}</span>
      <span className="font-mono text-11 text-ink-1">{m.dur}</span>
      <span className="font-mono text-11 text-ink-1">{m.speakers}</span>
      <div className="flex gap-1">
        {m.tags.map((t) => (
          <Pill key={t} tone="outline">
            {t}
          </Pill>
        ))}
      </div>
    </>
  );
  if (!m.path) {
    return (
      <div
        className={className}
        style={{ gridTemplateColumns: '120px minmax(0, 1fr) 80px 80px minmax(0, 1fr)' }}
      >
        {content}
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={onOpen}
      className={className}
      style={{ gridTemplateColumns: '120px minmax(0, 1fr) 80px 80px minmax(0, 1fr)' }}
    >
      {content}
    </button>
  );
}
