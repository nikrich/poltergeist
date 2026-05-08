import { useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { Eyebrow } from '../components/Eyebrow';
import { Catch } from '../components/Catch';
import { CAPTURE_ITEMS, type CaptureRecord } from '../lib/mocks/capture';
import { stub } from '../stores/toast';

const SOURCES = ['gmail', 'slack', 'notion', 'linear', 'calendar', 'github'];

function chipStyle(active: boolean): React.CSSProperties {
  return {
    fontFamily: 'var(--font-mono)',
    fontSize: 11,
    padding: '4px 10px',
    borderRadius: 4,
    background: active ? 'rgba(197,255,61,0.16)' : 'transparent',
    color: active ? 'var(--neon)' : 'var(--ink-1)',
    border: `1px solid ${active ? 'rgba(197,255,61,0.30)' : 'var(--hairline-2)'}`,
    cursor: 'pointer',
  };
}

export function CaptureScreen() {
  const [selected, setSelected] = useState<number>(1);
  const [filter, setFilter] = useState<string>('all');
  const item = CAPTURE_ITEMS.find((c) => c.id === selected);
  const filtered = CAPTURE_ITEMS.filter((c) => filter === 'all' || c.source === filter);
  const unread = CAPTURE_ITEMS.filter((c) => c.unread).length;

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
        title="capture"
        subtitle={`${unread} unread · ${CAPTURE_ITEMS.length} today`}
        right={
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="check-check" size={13} />}
              onClick={() => stub(3)}
            >
              mark all read
            </Btn>
            <Btn
              variant="secondary"
              size="sm"
              icon={<Lucide name="filter" size={13} />}
              onClick={() => stub(3)}
            >
              filters
            </Btn>
          </div>
        }
      />

      {/* source filter strip */}
      <div
        style={{
          padding: '12px 24px',
          borderBottom: '1px solid var(--hairline)',
          display: 'flex',
          gap: 6,
          alignItems: 'center',
          flexShrink: 0,
        }}
      >
        <button onClick={() => setFilter('all')} style={chipStyle(filter === 'all')}>
          all
        </button>
        {SOURCES.map((s) => (
          <button key={s} onClick={() => setFilter(s)} style={chipStyle(filter === s)}>
            <img
              src={`/assets/connectors/${s}.svg`}
              alt=""
              style={{
                width: 11,
                height: 11,
                marginRight: 4,
                verticalAlign: -1,
              }}
            />
            {s}
          </button>
        ))}
      </div>

      <div
        style={{
          flex: 1,
          display: 'grid',
          gridTemplateColumns: '1fr 480px',
          overflow: 'hidden',
        }}
      >
        {/* List */}
        <div style={{ overflowY: 'auto', padding: '12px 8px' }}>
          {filtered.map((c) => (
            <CaptureRow
              key={c.id}
              c={c}
              selected={selected === c.id}
              onClick={() => setSelected(c.id)}
            />
          ))}
        </div>

        {/* Detail */}
        {item && <CaptureDetail c={item} />}
      </div>
    </div>
  );
}

interface CaptureRowProps {
  c: CaptureRecord;
  selected: boolean;
  onClick: () => void;
}

function CaptureRow({ c, selected, onClick }: CaptureRowProps) {
  return (
    <div
      onClick={onClick}
      style={{
        display: 'grid',
        gridTemplateColumns: '20px 14px 1fr auto',
        gap: 10,
        alignItems: 'center',
        padding: '10px 14px',
        borderRadius: 6,
        cursor: 'pointer',
        marginBottom: 2,
        background: selected ? 'var(--bg-vellum)' : 'transparent',
        borderLeft: selected ? '2px solid var(--neon)' : '2px solid transparent',
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: c.unread ? 'var(--neon)' : 'transparent',
          justifySelf: 'center',
        }}
      />
      <img src={`/assets/connectors/${c.source}.svg`} alt="" style={{ width: 13, height: 13 }} />
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span
            style={{
              fontSize: 13,
              color: 'var(--ink-0)',
              fontWeight: c.unread ? 500 : 400,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {c.title}
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              color: 'var(--ink-3)',
              whiteSpace: 'nowrap',
            }}
          >
            {c.from}
          </span>
        </div>
        <div
          style={{
            fontSize: 11,
            color: 'var(--ink-2)',
            marginTop: 2,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            fontFamily: 'var(--font-display)',
            fontStyle: 'italic',
          }}
        >
          {c.snippet}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 4 }}>
        {c.tags.slice(0, 1).map((t) => (
          <Pill key={t} tone="outline">
            {t}
          </Pill>
        ))}
      </div>
    </div>
  );
}

interface CaptureDetailProps {
  c: CaptureRecord;
}

function CaptureDetail({ c }: CaptureDetailProps) {
  return (
    <aside
      style={{
        borderLeft: '1px solid var(--hairline)',
        background: 'var(--bg-vellum)',
        overflowY: 'auto',
        padding: 24,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          marginBottom: 14,
        }}
      >
        <img src={`/assets/connectors/${c.source}.svg`} alt="" style={{ width: 18, height: 18 }} />
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--ink-2)',
          }}
        >
          {c.source} · {c.from}
        </span>
        <div style={{ flex: 1 }} />
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="external-link" size={12} />}
          onClick={() => stub(3)}
        />
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="archive" size={12} />}
          onClick={() => stub(3)}
        />
      </div>
      <h3
        style={{
          margin: 0,
          fontFamily: 'var(--font-display)',
          fontSize: 22,
          fontWeight: 600,
          color: 'var(--ink-0)',
          letterSpacing: '-0.025em',
          lineHeight: 1.15,
        }}
      >
        {c.title}
      </h3>
      <p
        style={{
          marginTop: 14,
          fontFamily: 'var(--font-display)',
          fontStyle: 'italic',
          fontSize: 16,
          color: 'var(--ink-0)',
          lineHeight: 1.55,
        }}
      >
        &ldquo;{c.snippet}&rdquo;
      </p>

      <div style={{ marginTop: 24 }}>
        <Eyebrow style={{ marginBottom: 10 }}>ghostbrain extracted</Eyebrow>
        <div
          style={{
            background: 'var(--bg-paper)',
            border: '1px solid var(--hairline)',
            borderRadius: 8,
            padding: 14,
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
          }}
        >
          <Catch icon="check-square" text="action: ping mira about thursday" />
          <Catch icon="link" text="ref: design crit · onboarding v3" />
          <Catch icon="user" text="people: theo, mira" />
        </div>
      </div>

      <div style={{ marginTop: 20 }}>
        <Eyebrow style={{ marginBottom: 10 }}>destination</Eyebrow>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '10px 12px',
            background: 'var(--bg-paper)',
            border: '1px solid var(--hairline)',
            borderRadius: 6,
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
            ~/brain/Daily/2026-05-08.md
          </span>
        </div>
      </div>

      <div style={{ marginTop: 24, display: 'flex', gap: 8 }}>
        <Btn
          variant="primary"
          size="sm"
          icon={<Lucide name="file-down" size={13} color="#0E0F12" />}
          onClick={() => stub(3)}
        >
          save to vault
        </Btn>
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="bell-off" size={13} />}
          onClick={() => stub(3)}
        >
          mute thread
        </Btn>
      </div>
    </aside>
  );
}
