import { useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { Eyebrow } from '../components/Eyebrow';
import { Toggle } from '../components/Toggle';
import { CONNECTORS, type Connector, type ConnectorState } from '../lib/mocks/connectors';
import { stub } from '../stores/toast';

type Filter = 'all' | ConnectorState;

const FILTERS: Filter[] = ['all', 'on', 'err', 'off'];

const filterLabel = (f: Filter): string =>
  f === 'on' ? 'connected' : f === 'err' ? 'error' : f === 'off' ? 'disconnected' : 'all';

export function ConnectorsScreen() {
  const [selectedId, setSelectedId] = useState<string>(CONNECTORS[0]!.id);
  const [filter, setFilter] = useState<Filter>('all');
  const filtered = CONNECTORS.filter((c) => filter === 'all' || c.state === filter);
  const selected = CONNECTORS.find((c) => c.id === selectedId)!;

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        background: 'var(--bg-paper)',
      }}
    >
      <TopBar
        title="connectors"
        subtitle="6 of 7 · syncing live"
        right={
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn
              variant="secondary"
              size="sm"
              icon={<Lucide name="refresh-cw" size={13} />}
              onClick={() => stub(3)}
            >
              sync all
            </Btn>
            <Btn
              variant="primary"
              size="sm"
              icon={<Lucide name="plus" size={13} color="#0E0F12" />}
              onClick={() => stub(3)}
            >
              add connector
            </Btn>
          </div>
        }
      />

      <div
        style={{
          flex: 1,
          display: 'grid',
          gridTemplateColumns: '1fr 380px',
          overflow: 'hidden',
        }}
      >
        {/* List */}
        <div style={{ overflowY: 'auto', padding: '20px 24px' }}>
          {/* filter chips */}
          <div
            style={{
              display: 'flex',
              gap: 6,
              marginBottom: 16,
              alignItems: 'center',
            }}
          >
            <Eyebrow style={{ marginRight: 4 }}>filter</Eyebrow>
            {FILTERS.map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  padding: '4px 10px',
                  borderRadius: 4,
                  background: filter === f ? 'rgba(197,255,61,0.16)' : 'transparent',
                  color: filter === f ? 'var(--neon)' : 'var(--ink-1)',
                  border: `1px solid ${
                    filter === f ? 'rgba(197,255,61,0.30)' : 'var(--hairline-2)'
                  }`,
                  cursor: 'pointer',
                }}
              >
                {filterLabel(f)}
              </button>
            ))}
          </div>

          {/* table header */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '32px 1fr 100px 120px 120px 90px',
              gap: 12,
              padding: '0 14px 8px',
              borderBottom: '1px solid var(--hairline)',
            }}
          >
            <div />
            <Eyebrow>app</Eyebrow>
            <Eyebrow style={{ textAlign: 'right' }}>indexed</Eyebrow>
            <Eyebrow>last sync</Eyebrow>
            <Eyebrow>throughput</Eyebrow>
            <Eyebrow style={{ textAlign: 'right' }}>status</Eyebrow>
          </div>

          <div
            style={{
              marginTop: 6,
              display: 'flex',
              flexDirection: 'column',
              gap: 2,
            }}
          >
            {filtered.map((c) => (
              <ConnectorRow
                key={c.id}
                c={c}
                selected={selectedId === c.id}
                onClick={() => setSelectedId(c.id)}
              />
            ))}
            <AddConnectorRow />
          </div>
        </div>

        {/* Detail panel */}
        <ConnectorDetail c={selected} />
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

interface ConnectorRowProps {
  c: Connector;
  selected: boolean;
  onClick: () => void;
}

const TONES: Record<ConnectorState, 'neon' | 'oxblood' | 'outline'> = {
  on: 'neon',
  err: 'oxblood',
  off: 'outline',
};

const STATE_LABELS: Record<ConnectorState, string> = {
  on: 'connected',
  err: 'error',
  off: 'off',
};

function ConnectorRow({ c, selected, onClick }: ConnectorRowProps) {
  const [hover, setHover] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'grid',
        gridTemplateColumns: '32px 1fr 100px 120px 120px 90px',
        gap: 12,
        alignItems: 'center',
        padding: '12px 14px',
        borderRadius: 6,
        cursor: 'pointer',
        background: selected ? 'var(--bg-vellum)' : hover ? 'var(--bg-vellum)' : 'transparent',
        border: `1px solid ${selected ? 'var(--hairline-2)' : 'transparent'}`,
        opacity: c.state === 'off' ? 0.65 : 1,
      }}
    >
      <img
        src={'/' + c.src}
        alt=""
        style={{
          width: 22,
          height: 22,
          filter: c.state === 'off' ? 'grayscale(1)' : 'none',
        }}
      />
      <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
        <span style={{ fontSize: 13, color: 'var(--ink-0)', fontWeight: 500 }}>{c.name}</span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--ink-2)',
          }}
        >
          {c.account}
        </span>
      </div>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--ink-1)',
          textAlign: 'right',
        }}
      >
        {c.state === 'off' ? '—' : c.count.toLocaleString()}
      </span>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: c.state === 'err' ? 'var(--oxblood)' : 'var(--ink-2)',
        }}
      >
        {c.last}
      </span>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--ink-2)',
        }}
      >
        {c.throughput}
      </span>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Pill tone={TONES[c.state]}>{STATE_LABELS[c.state]}</Pill>
      </div>
    </div>
  );
}

function AddConnectorRow() {
  return (
    <div
      style={{
        marginTop: 8,
        padding: '14px',
        borderRadius: 6,
        border: '1px dashed var(--hairline-2)',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        cursor: 'pointer',
        color: 'var(--ink-2)',
        fontSize: 13,
      }}
    >
      <Lucide name="plus" size={14} />
      <span>request a connector — figma, intercom, hubspot, anywhere else</span>
    </div>
  );
}

interface ConnectorDetailProps {
  c: Connector;
}

function ConnectorDetail({ c }: ConnectorDetailProps) {
  return (
    <aside
      style={{
        borderLeft: '1px solid var(--hairline)',
        background: 'var(--bg-vellum)',
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* hero */}
      <div
        className="gb-noise"
        style={{
          padding: 24,
          borderBottom: '1px solid var(--hairline)',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: -40,
            right: -40,
            width: 200,
            height: 200,
            background: `radial-gradient(circle, ${c.color}22 0%, transparent 60%)`,
            pointerEvents: 'none',
          }}
        />
        <div
          style={{
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            marginBottom: 14,
          }}
        >
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 12,
              background: 'var(--bg-paper)',
              border: '1px solid var(--hairline)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <img src={'/' + c.src} alt="" style={{ width: 32, height: 32 }} />
          </div>
          <div style={{ flex: 1 }}>
            <div
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 22,
                fontWeight: 600,
                color: 'var(--ink-0)',
                letterSpacing: '-0.025em',
              }}
            >
              {c.name}
            </div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--ink-2)',
                marginTop: 2,
              }}
            >
              {c.account}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          {c.state === 'off' && (
            <Btn
              variant="primary"
              size="sm"
              icon={<Lucide name="link" size={13} color="#0E0F12" />}
              onClick={() => stub(3)}
            >
              connect {c.name}
            </Btn>
          )}
          {c.state === 'err' && (
            <Btn
              variant="primary"
              size="sm"
              icon={<Lucide name="refresh-cw" size={13} color="#0E0F12" />}
              onClick={() => stub(3)}
            >
              reauthorize
            </Btn>
          )}
          {c.state === 'on' && (
            <>
              <Btn
                variant="secondary"
                size="sm"
                icon={<Lucide name="refresh-cw" size={13} />}
                onClick={() => stub(3)}
              >
                sync now
              </Btn>
              <Btn
                variant="ghost"
                size="sm"
                icon={<Lucide name="pause" size={13} />}
                onClick={() => stub(3)}
              >
                pause
              </Btn>
            </>
          )}
        </div>
      </div>

      {/* details */}
      <div
        style={{
          padding: '20px 24px',
          display: 'flex',
          flexDirection: 'column',
          gap: 22,
        }}
      >
        {c.state === 'err' && (
          <div
            style={{
              background: 'rgba(255,107,90,0.08)',
              border: '1px solid rgba(255,107,90,0.25)',
              borderRadius: 6,
              padding: 12,
              display: 'flex',
              gap: 10,
            }}
          >
            <Lucide name="alert-triangle" size={14} color="var(--oxblood)" />
            <div style={{ flex: 1 }}>
              <div
                style={{
                  fontSize: 12,
                  color: 'var(--oxblood)',
                  fontWeight: 500,
                }}
              >
                oauth token expired
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: 'var(--ink-1)',
                  marginTop: 2,
                  lineHeight: 1.4,
                }}
              >
                github stopped accepting our token 2 days ago. one click and it&rsquo;s quiet again.
              </div>
            </div>
          </div>
        )}

        <DetailBlock label="indexed">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <Stat
              label="items"
              value={c.state === 'off' ? '—' : c.count.toLocaleString()}
              delta={c.throughput}
            />
            <Stat label="last sync" value={c.last} delta="auto · every 5m" />
          </div>
        </DetailBlock>

        <DetailBlock label="what ghostbrain pulls">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {c.pulls.map((p) => (
              <Pill key={p} tone="fog">
                {p}
              </Pill>
            ))}
          </div>
        </DetailBlock>

        <DetailBlock label="oauth scopes">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {c.scopes.map((s) => (
              <div
                key={s}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  color: 'var(--ink-1)',
                }}
              >
                <Lucide name="check" size={12} color="var(--neon)" />
                <span>{s}</span>
              </div>
            ))}
          </div>
        </DetailBlock>

        <DetailBlock label="vault destination">
          <div
            style={{
              background: 'var(--bg-paper)',
              border: '1px solid var(--hairline)',
              borderRadius: 6,
              padding: '10px 12px',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
            }}
          >
            <Lucide name="folder" size={13} color="var(--ink-2)" />
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--ink-0)',
                flex: 1,
              }}
            >
              ~/brain/sources/{c.name}
            </span>
            <Lucide name="external-link" size={11} color="var(--ink-3)" />
          </div>
        </DetailBlock>

        <DetailBlock label="filters">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Toggle label="ignore promotional & social" on={true} />
            <Toggle label="skip messages older than 90 days" on={false} />
            <Toggle label="extract action items" on={true} />
          </div>
        </DetailBlock>

        {c.state !== 'off' && (
          <Btn
            variant="danger"
            size="sm"
            icon={<Lucide name="unplug" size={13} />}
            style={{ alignSelf: 'flex-start', marginTop: 8 }}
            onClick={() => stub(3)}
          >
            disconnect
          </Btn>
        )}
      </div>
    </aside>
  );
}

interface DetailBlockProps {
  label: string;
  children: React.ReactNode;
}

function DetailBlock({ label, children }: DetailBlockProps) {
  return (
    <div>
      <Eyebrow style={{ marginBottom: 8 }}>{label}</Eyebrow>
      {children}
    </div>
  );
}

interface StatProps {
  label: string;
  value: string;
  delta: string;
}

function Stat({ label, value, delta }: StatProps) {
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
          color: 'var(--ink-0)',
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
          color: 'var(--ink-2)',
          marginTop: 2,
        }}
      >
        {delta}
      </div>
    </div>
  );
}
