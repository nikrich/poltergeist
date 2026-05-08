import { useEffect, useMemo, useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { Eyebrow } from '../components/Eyebrow';
import { Panel } from '../components/Panel';
import { Catch } from '../components/Catch';
import { useMeeting } from '../stores/meeting';
import { stub } from '../stores/toast';
import {
  PARTICIPANTS,
  TRANSCRIPT,
  HISTORY,
  SPEAKER_AIRTIME,
  type Participant,
  type TranscriptLine,
  type PastMeeting,
} from '../lib/mocks/meetings';
import { mmss } from '../lib/format';

export function MeetingsScreen() {
  const { phase, startedAt, start, stop, reset } = useMeeting();
  return (
    <div className="flex-1 overflow-y-auto bg-paper">
      <TopBar
        title="meetings"
        subtitle={phase === 'recording' ? '· recording in progress' : '47 in vault · 2 today'}
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

      {phase === 'pre' && <PreMeeting onStart={start} />}
      {phase === 'recording' && startedAt !== null && (
        <ActiveRecording startedAt={startedAt} onStop={stop} />
      )}
      {phase === 'post' && <PostMeeting onClose={reset} />}

      <MeetingHistory />
    </div>
  );
}

// ── Pre-meeting (lobby) ────────────────────────────────────────────────────
interface PreMeetingProps {
  onStart: () => void;
}

function PreMeeting({ onStart }: PreMeetingProps) {
  return (
    <div className="max-w-[1100px] px-8 py-6">
      <div className="gb-noise relative grid grid-cols-[1.3fr_1fr] gap-8 overflow-hidden rounded-lg border border-hairline bg-vellum p-8">
        <div
          className="pointer-events-none absolute -right-[100px] -top-[100px] h-[400px] w-[400px]"
          style={{
            background: 'radial-gradient(circle, rgba(197,255,61,0.08) 0%, transparent 60%)',
          }}
        />

        <div className="relative">
          <Pill tone="neon" className="mb-[14px]">
            <Lucide name="clock" size={9} /> starts in 23m
          </Pill>
          <h2 className="m-0 font-display text-32 font-semibold leading-[1.05] tracking-tighter text-ink-0">
            design crit · onboarding v3
          </h2>
          <div className="mt-3 flex items-center gap-4 font-mono text-11 text-ink-2">
            <span>
              <Lucide
                name="calendar"
                size={11}
                className="mr-[5px] align-[-2px] inline-block"
              />{' '}
              today · 11:00 — 11:30
            </span>
            <span>
              <Lucide
                name="map-pin"
                size={11}
                className="mr-[5px] align-[-2px] inline-block"
              />{' '}
              google meet
            </span>
          </div>

          <div className="mt-6 rounded-md border border-hairline bg-paper p-4">
            <Eyebrow className="mb-2">ghostbrain primed</Eyebrow>
            <ul className="m-0 flex list-none flex-col gap-[6px] p-0">
              {[
                'pulled 14 messages from #design-crit since last session',
                'linked GHO-241, GHO-247 from linear',
                '2 onboarding mocks in notion, last edited 2h ago',
                'transcript will land in ~/brain/Meetings/2026-05-08-design-crit.md',
              ].map((line, i) => (
                <li key={i} className="flex items-start gap-2 text-12 text-ink-1">
                  <Lucide name="check" size={11} color="var(--neon)" className="mt-1" />
                  <span>{line}</span>
                </li>
              ))}
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
              variant="secondary"
              size="lg"
              icon={<Lucide name="external-link" size={14} />}
              onClick={() => stub(4)}
            >
              open meet
            </Btn>
            <Btn variant="ghost" size="lg" onClick={() => stub(4)}>
              configure…
            </Btn>
          </div>
        </div>

        {/* Right: participants + audio preview */}
        <div className="relative flex flex-col gap-4">
          <Eyebrow>participants · 4</Eyebrow>
          <div className="flex flex-col gap-1">
            {PARTICIPANTS.map((p) => (
              <ParticipantRow key={p.name} {...p} />
            ))}
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
            <AudioSource icon="bluetooth" label="AirPods Pro" sub="not connected" active={false} />
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

function ParticipantRow({ name, role, color }: Participant) {
  return (
    <div className="flex items-center gap-[10px] rounded-sm px-2 py-[6px]">
      {/* intentional fixed color: first-letter avatar text stays dark on the
          per-participant bright background, regardless of theme */}
      <div
        className="flex h-6 w-6 items-center justify-center rounded-full text-11 font-semibold text-[#0E0F12]"
        style={{ background: color }}
      >
        {name[0]}
      </div>
      <span className="flex-1 text-12 text-ink-0">{name}</span>
      <span className="font-mono text-10 text-ink-2">{role}</span>
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
  return (
    <div
      className={`mb-1 flex cursor-pointer items-center gap-[10px] rounded-r6 border px-[10px] py-2 ${
        active
          ? 'border-neon/20 bg-neon/[0.08] opacity-100'
          : 'border-hairline bg-transparent opacity-55'
      }`}
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
  onStop: () => void;
}

function ActiveRecording({ startedAt, onStop }: ActiveRecordingProps) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const tick = () => setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [startedAt]);

  return (
    <div className="max-w-[1100px] px-8 py-6">
      {/* live banner */}
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
              design crit · onboarding v3
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
            variant="ghost"
            size="sm"
            icon={<Lucide name="pause" size={14} />}
            onClick={() => stub(4)}
          >
            pause
          </Btn>
          <Btn
            variant="record"
            size="md"
            // intentional fixed color: dark stop-square inside the always-bright oxblood record button
            icon={<span className="h-[9px] w-[9px] bg-[#0E0F12]" />}
            onClick={onStop}
          >
            stop
          </Btn>
        </div>
      </div>

      {/* live transcript + side rail */}
      <div className="grid grid-cols-[1.6fr_1fr] gap-4">
        <Panel
          title="live transcript"
          subtitle="diarized · 4 speakers"
          action={
            <div className="flex gap-[6px]">
              <Pill tone="moss">
                <Lucide name="check" size={9} /> auto-saving
              </Pill>
              <Btn
                variant="ghost"
                size="sm"
                icon={<Lucide name="bookmark" size={12} />}
                onClick={() => stub(4)}
              >
                mark
              </Btn>
            </div>
          }
        >
          <div className="flex max-h-[360px] flex-col gap-[14px] overflow-y-auto px-1 py-2">
            {TRANSCRIPT.map((line: TranscriptLine, i) => (
              <div
                key={i}
                className={`grid grid-cols-[64px_1fr] gap-3 ${line.live ? 'opacity-100' : 'opacity-90'}`}
              >
                <div className="flex flex-col items-start gap-[2px]">
                  {/* intentional fixed color: speaker initial reads dark on per-line bright avatar bg */}
                  <div
                    className="flex h-[22px] w-[22px] items-center justify-center rounded-full text-10 font-semibold text-[#0E0F12]"
                    style={{ background: line.color }}
                  >
                    {line.who[0]}
                  </div>
                  <div className="font-mono text-9 text-ink-3">{line.t}</div>
                </div>
                <div>
                  <div className="mb-[2px] text-11 lowercase text-ink-2">{line.who}</div>
                  <div className="text-14 leading-[1.55] text-ink-0">
                    {line.text}
                    {line.live && (
                      <span
                        className="ml-1 inline-block bg-neon"
                        style={{
                          width: 6,
                          height: 14,
                          verticalAlign: -2,
                          animation: 'gb-blink 1s steps(2) infinite',
                        }}
                      />
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <div className="flex flex-col gap-4">
          <Panel title="speakers" subtitle="airtime">
            {PARTICIPANTS.map((p, i) => (
              <div key={p.name} className="flex items-center gap-[10px] px-1 py-[6px]">
                <div
                  className="h-[18px] w-[18px] rounded-full"
                  style={{ background: p.color }}
                />
                <span className="flex-1 text-12 text-ink-0">{p.name}</span>
                <div className="h-1 w-[90px] overflow-hidden rounded-xs bg-paper">
                  <div
                    className="h-full"
                    style={{ width: `${SPEAKER_AIRTIME[i]}%`, background: p.color }}
                  />
                </div>
                <span className="w-8 text-right font-mono text-10 text-ink-2">
                  {SPEAKER_AIRTIME[i]}%
                </span>
              </div>
            ))}
          </Panel>

          <Panel title="ghost catches" subtitle="auto-extracted · live">
            <Catch icon="check-square" text="split connector picker out from vault setup" />
            <Catch icon="alert-circle" text="minimum one connected = soft requirement" />
            <Catch icon="link" text="ref: GHO-241, GHO-247" />
          </Panel>
        </div>
      </div>
    </div>
  );
}

// ── Post-meeting summary ──────────────────────────────────────────────────
interface PostMeetingProps {
  onClose: () => void;
}

function PostMeeting({ onClose }: PostMeetingProps) {
  return (
    <div className="max-w-[1100px] px-8 py-6">
      <div className="mb-4 rounded-lg border border-hairline bg-vellum p-7">
        <div className="mb-4 flex items-center gap-3">
          <Pill tone="moss">
            <Lucide name="check" size={9} /> wrapped · 28:14
          </Pill>
          <Pill tone="fog">just now</Pill>
          <div className="flex-1" />
          <Btn variant="ghost" size="sm" icon={<Lucide name="x" size={13} />} onClick={onClose} />
        </div>

        <h2 className="m-0 font-display text-28 font-semibold tracking-tighter text-ink-0">
          design crit · onboarding v3
        </h2>
        <div className="mt-1 font-mono text-11 text-ink-2">
          ~/brain/Meetings/2026-05-08-design-crit.md · 4 speakers · 312 lines
        </div>

        <div className="mt-5 grid grid-cols-[1.5fr_1fr] gap-4">
          <div className="rounded-md border border-hairline bg-paper p-[18px]">
            <Eyebrow className="mb-[10px]">tl;dr</Eyebrow>
            <p className="m-0 font-display text-16 italic leading-[1.5] text-ink-0">
              &ldquo;the third onboarding screen is doing too much. split the connector picker out,
              but require at least one connected before showing the dashboard — otherwise the
              welcome state is empty.&rdquo;
            </p>
            <div className="mt-4 flex gap-2">
              <Btn
                variant="primary"
                size="sm"
                // intentional fixed color: icon must read dark on the always-bright neon button
                icon={<Lucide name="file-down" size={13} color="#0E0F12" />}
                onClick={() => stub(4)}
              >
                save to vault
              </Btn>
              <Btn
                variant="secondary"
                size="sm"
                icon={<Lucide name="share" size={13} />}
                onClick={() => stub(4)}
              >
                share md
              </Btn>
              <Btn
                variant="ghost"
                size="sm"
                icon={<Lucide name="play" size={13} />}
                onClick={() => stub(4)}
              >
                play audio
              </Btn>
            </div>
          </div>

          <div className="rounded-md border border-hairline bg-paper p-[18px]">
            <Eyebrow className="mb-[10px]">action items · 3</Eyebrow>
            <Action who="jules" text="split connector picker into its own screen" />
            <Action who="mira" text="document 'min one connected' rule" />
            <Action who="you" text="redo welcome state mock by friday" />
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-4">
          <SmallStat label="words" value="3,841" />
          <SmallStat label="speakers" value="4" />
          <SmallStat label="links extracted" value="6" />
        </div>
      </div>
    </div>
  );
}

interface ActionProps {
  who: string;
  text: string;
}

function Action({ who, text }: ActionProps) {
  return (
    <div className="flex items-start gap-2 py-[6px]">
      <input
        type="checkbox"
        disabled
        className="mt-[3px] h-3 w-3 flex-shrink-0 cursor-not-allowed appearance-none rounded-sm border-[1.5px] border-ink-3 bg-transparent"
      />
      <div className="flex-1 text-12 leading-[1.5] text-ink-0">
        {text} <span className="font-mono text-10 text-neon">@{who}</span>
      </div>
    </div>
  );
}

interface SmallStatProps {
  label: string;
  value: string;
}

function SmallStat({ label, value }: SmallStatProps) {
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
  return (
    <div className="max-w-[1100px] px-8 pb-10 pt-2">
      <Panel
        title="past meetings"
        subtitle="47 in vault"
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
        {HISTORY.map((m: PastMeeting, i) => (
          <HistoryRow key={i} m={m} />
        ))}
      </Panel>
    </div>
  );
}

interface HistoryRowProps {
  m: PastMeeting;
}

function HistoryRow({ m }: HistoryRowProps) {
  return (
    <div
      className="grid cursor-pointer items-center gap-3 rounded-sm bg-transparent px-2 py-[10px] hover:bg-paper"
      style={{ gridTemplateColumns: '120px minmax(0, 1fr) 80px 80px minmax(0, 1fr)' }}
    >
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
    </div>
  );
}
