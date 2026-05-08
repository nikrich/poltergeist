import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { Eyebrow } from '../components/Eyebrow';
import { Panel } from '../components/Panel';
import { TopBar } from '../components/TopBar';
import { useNavigation } from '../stores/navigation';
import { stub } from '../stores/toast';
import {
  AGENDA,
  ACTIVITY,
  CONNECTOR_PULSES,
  CAUGHT_LATELY,
  SUGGESTIONS,
  STATS,
  type AgendaItem as AgendaItemData,
  type ActivityRow as ActivityRowData,
  type ConnectorPulse as ConnectorPulseData,
  type CaptureLatelyItem,
  type Suggestion as SuggestionData,
} from '../lib/mocks/today';

export function TodayScreen() {
  const setActive = useNavigation((s) => s.setActive);

  // Carry the per-row CTA next to the data so the JSX stays readable. The
  // mock array stays pristine; only the renderer knows about CTAs.
  const agendaCtas: React.ReactNode[] = [
    <Btn
      key="record"
      variant="primary"
      size="sm"
      // intentional fixed color: icon must read dark on the always-bright neon button
      icon={<Lucide name="mic" size={12} color="#0E0F12" />}
      onClick={() => setActive('meetings')}
    >
      record
    </Btn>,
    <Btn
      key="more"
      variant="ghost"
      size="sm"
      icon={<Lucide name="more-horizontal" size={12} />}
      onClick={() => stub(3)}
    />,
    <Pill key="recorded" tone="moss">
      <Lucide name="check" size={9} /> recorded
    </Pill>,
  ];

  return (
    <div className="flex-1 overflow-y-auto bg-paper">
      <TopBar
        title="today"
        subtitle="thursday · may 8"
        right={
          <div className="flex gap-2">
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="search" size={14} />}
              onClick={() => stub(3)}
            >
              ask…
              <kbd className="ml-2 rounded-xs bg-fog px-[5px] py-[1px] font-mono text-9 text-ink-2">
                ⌘K
              </kbd>
            </Btn>
            <Btn
              variant="secondary"
              size="sm"
              icon={<Lucide name="bell" size={14} />}
              onClick={() => stub(3)}
            />
          </div>
        }
      />

      <div className="flex max-w-[1100px] flex-col gap-6 px-8 pb-10 pt-6">
        {/* Hero greeting + ghost activity */}
        <div className="gb-noise relative grid grid-cols-[1.4fr_1fr] gap-7 overflow-hidden rounded-lg border border-hairline bg-vellum p-7">
          <div
            className="pointer-events-none absolute -right-20 -top-20 h-[360px] w-[360px]"
            style={{
              background: 'radial-gradient(circle, rgba(197,255,61,0.10) 0%, transparent 60%)',
            }}
          />

          <div className="relative z-[1]">
            <Eyebrow>good morning</Eyebrow>
            <h2 className="mb-0 mt-2 font-display text-38 font-semibold leading-[1.05] tracking-tightest text-ink-0">
              while you slept,
              <br />
              <span className="text-neon">ghostbrain caught</span>
              <br />
              241 things.
            </h2>
            <p className="mb-[18px] mt-[14px] max-w-[46ch] text-14 leading-[1.5] text-ink-1">
              4 connectors syncing. 2 meetings on your calendar today — one is ready to record.
            </p>
            <div className="flex gap-2">
              <Btn
                variant="primary"
                size="md"
                // intentional fixed color: icon must read dark on the always-bright neon button
                icon={<Lucide name="search" size={14} color="#0E0F12" />}
                onClick={() => stub(3)}
              >
                ask the archive
              </Btn>
              <Btn
                variant="secondary"
                size="md"
                onClick={() => setActive('meetings')}
                icon={<Lucide name="mic" size={14} />}
              >
                start recording
              </Btn>
            </div>
          </div>

          {/* mini stat grid */}
          <div className="relative z-[1] grid grid-cols-2 content-start gap-2">
            <Stat {...STATS.captured} tone="neon" />
            <Stat {...STATS.meetings} />
            <Stat {...STATS.followups} tone="oxblood" />
            <Stat {...STATS.vaultSize} />
          </div>
        </div>

        {/* Two-column: agenda + activity */}
        <div className="grid grid-cols-2 gap-4">
          {/* Agenda */}
          <Panel
            title="agenda"
            subtitle="2 events · today"
            action={
              <Btn
                variant="ghost"
                size="sm"
                iconRight={<Lucide name="arrow-right" size={12} />}
                onClick={() => stub(3)}
              >
                calendar
              </Btn>
            }
          >
            {AGENDA.map((item, i) => (
              <AgendaItem key={`${item.time}-${item.title}`} {...item} cta={agendaCtas[i]} />
            ))}
          </Panel>

          {/* Live activity feed */}
          <Panel
            title="ghost activity"
            subtitle="last 4 hours"
            action={
              <Pill tone="neon">
                <span className="h-[5px] w-[5px] rounded-full bg-neon" /> live
              </Pill>
            }
          >
            {ACTIVITY.map((row, i) => (
              <ActivityRow key={`${row.source}-${row.subject}-${i}`} {...row} />
            ))}
          </Panel>
        </div>

        {/* Connector pulse strip */}
        <Panel
          title="connectors"
          subtitle="6 of 7 connected"
          action={
            <Btn
              variant="ghost"
              size="sm"
              onClick={() => setActive('connectors')}
              iconRight={<Lucide name="arrow-right" size={12} />}
            >
              manage
            </Btn>
          }
        >
          <div className="grid grid-cols-7 gap-2">
            {CONNECTOR_PULSES.map((c) => (
              <ConnectorPulse key={c.name} {...c} />
            ))}
          </div>
        </Panel>

        {/* Bottom row — recent capture + suggestions */}
        <div className="grid grid-cols-[1.3fr_1fr] gap-4">
          <Panel
            title="caught lately"
            action={
              <Btn
                variant="ghost"
                size="sm"
                onClick={() => setActive('capture')}
                iconRight={<Lucide name="arrow-right" size={12} />}
              >
                inbox
              </Btn>
            }
          >
            {CAUGHT_LATELY.map((item) => (
              <CaptureItem key={`${item.source}-${item.title}`} {...item} />
            ))}
          </Panel>

          <Panel title="suggested by ghostbrain" subtitle="quiet hunches">
            {SUGGESTIONS.map((s) => (
              <Suggestion key={s.title} {...s} />
            ))}
          </Panel>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

interface StatProps {
  label: string;
  value: string;
  delta: string;
  tone?: 'neon' | 'oxblood';
}

function Stat({ label, value, delta, tone }: StatProps) {
  return (
    <div className="rounded-md border border-hairline bg-paper p-[14px]">
      <Eyebrow>{label}</Eyebrow>
      <div
        className={`mt-1 font-display text-28 font-semibold leading-[1.1] tracking-tight-x ${
          tone === 'neon' ? 'text-neon' : 'text-ink-0'
        }`}
      >
        {value}
      </div>
      <div
        className={`mt-[2px] font-mono text-10 ${
          tone === 'oxblood' ? 'text-oxblood' : 'text-ink-2'
        }`}
      >
        {delta}
      </div>
    </div>
  );
}

interface AgendaItemProps extends AgendaItemData {
  cta?: React.ReactNode;
}

function AgendaItem({ time, dur, title, with: people, status, cta }: AgendaItemProps) {
  const recorded = status === 'recorded';
  return (
    <div
      className={`grid grid-cols-[52px_1fr_auto] items-center gap-[14px] rounded-r6 px-2 py-[10px] ${
        recorded ? 'opacity-70' : 'opacity-100'
      }`}
    >
      <div
        className={`border-l-2 border-neon pl-2 leading-[1.15] ${
          recorded ? 'opacity-50' : 'opacity-100'
        }`}
      >
        <div className="font-mono text-13 font-medium text-ink-0">{time}</div>
        <div className="font-mono text-9 text-ink-2">{dur}</div>
      </div>
      <div className="min-w-0">
        <div className="overflow-hidden text-ellipsis whitespace-nowrap text-13 font-medium text-ink-0">
          {title}
        </div>
        <div className="font-mono text-10 text-ink-2">with {people.join(', ')}</div>
      </div>
      {cta}
    </div>
  );
}

function ActivityRow({ source, verb, subject, time }: ActivityRowData) {
  return (
    <div className="flex items-center gap-[10px] rounded-sm px-[6px] py-2">
      <img
        src={`/assets/connectors/${source}.svg`}
        alt=""
        className="h-[14px] w-[14px] opacity-90"
      />
      <span className="font-mono text-10 text-ink-2">{verb}</span>
      <span className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-12 text-ink-0">
        {subject}
      </span>
      <span className="font-mono text-10 text-ink-3">{time}</span>
    </div>
  );
}

function ConnectorPulse({ name, state, count }: ConnectorPulseData) {
  const dotClass =
    state === 'on' ? 'bg-neon' : state === 'err' ? 'bg-oxblood' : 'bg-ink-3';
  return (
    <div
      className={`flex cursor-pointer flex-col items-center gap-1 rounded-r6 border border-hairline bg-paper px-2 py-[10px] ${
        state === 'off' ? 'opacity-50' : 'opacity-100'
      }`}
    >
      <div className="relative">
        <img
          src={`/assets/connectors/${name}.svg`}
          alt={name}
          className={`h-[22px] w-[22px] ${state === 'off' ? 'grayscale' : ''}`}
        />
        <span
          className={`absolute -bottom-[2px] -right-[2px] h-[7px] w-[7px] rounded-full border-[1.5px] border-paper ${dotClass}`}
        />
      </div>
      <div className="text-10 lowercase text-ink-1">{name}</div>
      <div className="font-mono text-9 text-ink-3">{count}</div>
    </div>
  );
}

function CaptureItem({ source, title, snippet, from }: CaptureLatelyItem) {
  return (
    <div
      className="cursor-pointer rounded-r6 px-2 py-[10px]"
      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-paper)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
    >
      <div className="mb-1 flex items-center gap-2">
        <img src={`/assets/connectors/${source}.svg`} alt="" className="h-3 w-3" />
        <span className="text-12 font-medium text-ink-0">{title}</span>
        <span className="ml-auto font-mono text-9 text-ink-3">{from}</span>
      </div>
      <div className="font-display text-13 italic leading-[1.4] text-ink-1">
        &ldquo;{snippet}&rdquo;
      </div>
    </div>
  );
}

function Suggestion({ icon, title, body, accent }: SuggestionData) {
  return (
    <div
      className={`flex cursor-pointer gap-[10px] rounded-r6 px-3 py-[10px] ${
        accent
          ? 'border border-[rgba(197,255,61,0.18)] bg-[rgba(197,255,61,0.06)]'
          : 'border border-transparent bg-transparent'
      }`}
    >
      <div
        className={`flex h-[26px] w-[26px] flex-shrink-0 items-center justify-center rounded-sm ${
          accent ? 'bg-[rgba(197,255,61,0.15)]' : 'bg-paper'
        }`}
      >
        <Lucide name={icon} size={13} color={accent ? 'var(--neon)' : 'var(--ink-1)'} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-12 font-medium text-ink-0">{title}</div>
        <div className="mt-[2px] text-11 leading-[1.4] text-ink-2">{body}</div>
      </div>
    </div>
  );
}
