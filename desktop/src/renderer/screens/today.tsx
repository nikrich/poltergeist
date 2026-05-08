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
    <div style={{ flex: 1, overflowY: 'auto', background: 'var(--bg-paper)' }}>
      <TopBar
        title="today"
        subtitle="thursday · may 8"
        right={
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="search" size={14} />}
              onClick={() => stub(3)}
            >
              ask…
              <kbd
                style={{
                  marginLeft: 8,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 9,
                  padding: '1px 5px',
                  borderRadius: 3,
                  background: 'var(--bg-fog)',
                  color: 'var(--ink-2)',
                }}
              >
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

      <div
        style={{
          padding: '24px 32px 40px',
          display: 'flex',
          flexDirection: 'column',
          gap: 24,
          maxWidth: 1100,
        }}
      >
        {/* Hero greeting + ghost activity */}
        <div
          className="gb-noise"
          style={{
            position: 'relative',
            overflow: 'hidden',
            background: 'var(--bg-vellum)',
            border: '1px solid var(--hairline)',
            borderRadius: 12,
            padding: 28,
            display: 'grid',
            gridTemplateColumns: '1.4fr 1fr',
            gap: 28,
          }}
        >
          <div
            style={{
              position: 'absolute',
              top: -80,
              right: -80,
              width: 360,
              height: 360,
              background: 'radial-gradient(circle, rgba(197,255,61,0.10) 0%, transparent 60%)',
              pointerEvents: 'none',
            }}
          />

          <div style={{ position: 'relative', zIndex: 1 }}>
            <Eyebrow>good morning</Eyebrow>
            <h2
              style={{
                margin: '8px 0 0',
                fontFamily: 'var(--font-display)',
                fontSize: 38,
                fontWeight: 600,
                color: 'var(--ink-0)',
                letterSpacing: '-0.035em',
                lineHeight: 1.05,
              }}
            >
              while you slept,
              <br />
              <span style={{ color: 'var(--neon)' }}>ghostbrain caught</span>
              <br />
              241 things.
            </h2>
            <p
              style={{
                margin: '14px 0 18px',
                color: 'var(--ink-1)',
                fontSize: 14,
                maxWidth: '46ch',
                lineHeight: 1.5,
              }}
            >
              4 connectors syncing. 2 meetings on your calendar today — one is ready to record.
            </p>
            <div style={{ display: 'flex', gap: 8 }}>
              <Btn
                variant="primary"
                size="md"
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
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 8,
              alignContent: 'start',
              position: 'relative',
              zIndex: 1,
            }}
          >
            <Stat {...STATS.captured} tone="neon" />
            <Stat {...STATS.meetings} />
            <Stat {...STATS.followups} tone="oxblood" />
            <Stat {...STATS.vaultSize} />
          </div>
        </div>

        {/* Two-column: agenda + activity */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
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
                <span
                  style={{
                    width: 5,
                    height: 5,
                    borderRadius: '50%',
                    background: 'var(--neon)',
                  }}
                />{' '}
                live
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
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 8 }}>
            {CONNECTOR_PULSES.map((c) => (
              <ConnectorPulse key={c.name} {...c} />
            ))}
          </div>
        </Panel>

        {/* Bottom row — recent capture + suggestions */}
        <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: 16 }}>
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
    <div
      style={{
        background: 'var(--bg-paper)',
        border: '1px solid var(--hairline)',
        borderRadius: 8,
        padding: 14,
      }}
    >
      <Eyebrow>{label}</Eyebrow>
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 28,
          fontWeight: 600,
          color: tone === 'neon' ? 'var(--neon)' : 'var(--ink-0)',
          letterSpacing: '-0.025em',
          lineHeight: 1.1,
          marginTop: 4,
        }}
      >
        {value}
      </div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: tone === 'oxblood' ? 'var(--oxblood)' : 'var(--ink-2)',
          marginTop: 2,
        }}
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
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '52px 1fr auto',
        gap: 14,
        alignItems: 'center',
        padding: '10px 8px',
        borderRadius: 6,
        opacity: status === 'recorded' ? 0.7 : 1,
      }}
    >
      <div
        style={{
          borderLeft: '2px solid var(--neon)',
          paddingLeft: 8,
          lineHeight: 1.15,
          opacity: status === 'recorded' ? 0.5 : 1,
        }}
      >
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            color: 'var(--ink-0)',
            fontWeight: 500,
          }}
        >
          {time}
        </div>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 9,
            color: 'var(--ink-2)',
          }}
        >
          {dur}
        </div>
      </div>
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontSize: 13,
            color: 'var(--ink-0)',
            fontWeight: 500,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {title}
        </div>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--ink-2)',
          }}
        >
          with {people.join(', ')}
        </div>
      </div>
      {cta}
    </div>
  );
}

function ActivityRow({ source, verb, subject, time }: ActivityRowData) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 6px',
        borderRadius: 4,
      }}
    >
      <img
        src={`/assets/connectors/${source}.svg`}
        alt=""
        style={{ width: 14, height: 14, opacity: 0.9 }}
      />
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--ink-2)',
        }}
      >
        {verb}
      </span>
      <span
        style={{
          fontSize: 12,
          color: 'var(--ink-0)',
          flex: 1,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {subject}
      </span>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--ink-3)',
        }}
      >
        {time}
      </span>
    </div>
  );
}

function ConnectorPulse({ name, state, count }: ConnectorPulseData) {
  const dotColor =
    state === 'on' ? 'var(--neon)' : state === 'err' ? 'var(--oxblood)' : 'var(--ink-3)';
  return (
    <div
      style={{
        background: 'var(--bg-paper)',
        border: '1px solid var(--hairline)',
        borderRadius: 6,
        padding: '10px 8px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 4,
        cursor: 'pointer',
        opacity: state === 'off' ? 0.5 : 1,
      }}
    >
      <div style={{ position: 'relative' }}>
        <img
          src={`/assets/connectors/${name}.svg`}
          alt={name}
          style={{
            width: 22,
            height: 22,
            filter: state === 'off' ? 'grayscale(1)' : 'none',
          }}
        />
        <span
          style={{
            position: 'absolute',
            bottom: -2,
            right: -2,
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: dotColor,
            border: '1.5px solid var(--bg-paper)',
          }}
        />
      </div>
      <div style={{ fontSize: 10, color: 'var(--ink-1)', textTransform: 'lowercase' }}>{name}</div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9,
          color: 'var(--ink-3)',
        }}
      >
        {count}
      </div>
    </div>
  );
}

function CaptureItem({ source, title, snippet, from }: CaptureLatelyItem) {
  return (
    <div
      style={{ padding: '10px 8px', borderRadius: 6, cursor: 'pointer' }}
      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-paper)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <img src={`/assets/connectors/${source}.svg`} alt="" style={{ width: 12, height: 12 }} />
        <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--ink-0)' }}>{title}</span>
        <span
          style={{
            marginLeft: 'auto',
            fontFamily: 'var(--font-mono)',
            fontSize: 9,
            color: 'var(--ink-3)',
          }}
        >
          {from}
        </span>
      </div>
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontStyle: 'italic',
          fontSize: 13,
          color: 'var(--ink-1)',
          lineHeight: 1.4,
        }}
      >
        &ldquo;{snippet}&rdquo;
      </div>
    </div>
  );
}

function Suggestion({ icon, title, body, accent }: SuggestionData) {
  return (
    <div
      style={{
        padding: '10px 12px',
        borderRadius: 6,
        background: accent ? 'rgba(197,255,61,0.06)' : 'transparent',
        border: accent ? '1px solid rgba(197,255,61,0.18)' : '1px solid transparent',
        display: 'flex',
        gap: 10,
        cursor: 'pointer',
      }}
    >
      <div
        style={{
          width: 26,
          height: 26,
          borderRadius: 5,
          flexShrink: 0,
          background: accent ? 'rgba(197,255,61,0.15)' : 'var(--bg-paper)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Lucide name={icon} size={13} color={accent ? 'var(--neon)' : 'var(--ink-1)'} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--ink-0)' }}>{title}</div>
        <div
          style={{
            fontSize: 11,
            color: 'var(--ink-2)',
            lineHeight: 1.4,
            marginTop: 2,
          }}
        >
          {body}
        </div>
      </div>
    </div>
  );
}
