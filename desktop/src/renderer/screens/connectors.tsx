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

// Custom 6-col grid: minmax(0, 1fr) has no clean Tailwind utility, so the
// template stays inline. Used for both header row and data rows so columns
// align across them.
const ROW_GRID = '32px minmax(0, 1fr) 100px 120px 120px 90px';

export function ConnectorsScreen() {
  const [selectedId, setSelectedId] = useState<string>(CONNECTORS[0]!.id);
  const [filter, setFilter] = useState<Filter>('all');
  const filtered = CONNECTORS.filter((c) => filter === 'all' || c.state === filter);
  const selected = CONNECTORS.find((c) => c.id === selectedId)!;

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar
        title="connectors"
        subtitle="6 of 7 · syncing live"
        right={
          <div className="flex gap-2">
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
              // intentional fixed color: icon must read dark on the always-bright neon button
              icon={<Lucide name="plus" size={13} color="#0E0F12" />}
              onClick={() => stub(3)}
            >
              add connector
            </Btn>
          </div>
        }
      />

      <div className="grid flex-1 grid-cols-[1fr_380px] overflow-hidden">
        {/* List */}
        <div className="overflow-y-auto px-6 py-5">
          {/* filter chips */}
          <div className="mb-4 flex items-center gap-[6px]">
            <Eyebrow className="mr-1">filter</Eyebrow>
            {FILTERS.map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`cursor-pointer rounded-sm border px-[10px] py-1 font-mono text-11 ${
                  filter === f
                    ? 'border-neon/30 bg-neon/15 text-neon'
                    : 'border-hairline-2 bg-transparent text-ink-1'
                }`}
              >
                {filterLabel(f)}
              </button>
            ))}
          </div>

          {/* table header */}
          <div
            className="grid gap-3 border-b border-hairline px-[14px] pb-2"
            style={{ gridTemplateColumns: ROW_GRID }}
          >
            <div />
            <Eyebrow>app</Eyebrow>
            <Eyebrow className="text-right">indexed</Eyebrow>
            <Eyebrow>last sync</Eyebrow>
            <Eyebrow>throughput</Eyebrow>
            <Eyebrow className="text-right">status</Eyebrow>
          </div>

          <div className="mt-[6px] flex flex-col gap-[2px]">
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
  const bgClass = selected || hover ? 'bg-vellum' : 'bg-transparent';
  const borderClass = selected ? 'border-hairline-2' : 'border-transparent';
  const opacityClass = c.state === 'off' ? 'opacity-65' : 'opacity-100';
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className={`grid cursor-pointer items-center gap-3 rounded-r6 border px-[14px] py-3 ${bgClass} ${borderClass} ${opacityClass}`}
      style={{ gridTemplateColumns: ROW_GRID }}
    >
      <img
        src={'/' + c.src}
        alt=""
        width={22}
        height={22}
        className={c.state === 'off' ? 'grayscale' : ''}
      />
      <div className="flex min-w-0 flex-col leading-[1.2]">
        <span className="text-13 font-medium text-ink-0">{c.name}</span>
        <span className="overflow-hidden text-ellipsis whitespace-nowrap font-mono text-10 text-ink-2">
          {c.account}
        </span>
      </div>
      <span className="text-right font-mono text-11 text-ink-1">
        {c.state === 'off' ? '—' : c.count.toLocaleString()}
      </span>
      <span
        className={`font-mono text-11 ${c.state === 'err' ? 'text-oxblood' : 'text-ink-2'}`}
      >
        {c.last}
      </span>
      <span className="font-mono text-11 text-ink-2">{c.throughput}</span>
      <div className="flex justify-end">
        <Pill tone={TONES[c.state]}>{STATE_LABELS[c.state]}</Pill>
      </div>
    </div>
  );
}

function AddConnectorRow() {
  return (
    <div className="mt-2 flex cursor-pointer items-center gap-[10px] rounded-r6 border border-dashed border-hairline-2 p-[14px] text-13 text-ink-2">
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
    <aside className="flex flex-col overflow-y-auto border-l border-hairline bg-vellum">
      {/* hero */}
      <div className="gb-noise relative overflow-hidden border-b border-hairline p-6">
        <div
          className="pointer-events-none absolute -right-10 -top-10 h-[200px] w-[200px]"
          style={{
            background: `radial-gradient(circle, ${c.color}22 0%, transparent 60%)`,
          }}
        />
        <div className="relative mb-[14px] flex items-center gap-[14px]">
          <div className="flex h-14 w-14 items-center justify-center rounded-lg border border-hairline bg-paper">
            <img src={'/' + c.src} alt="" width={32} height={32} />
          </div>
          <div className="flex-1">
            <div className="font-display text-22 font-semibold tracking-tight-x text-ink-0">
              {c.name}
            </div>
            <div className="mt-[2px] font-mono text-10 text-ink-2">{c.account}</div>
          </div>
        </div>

        <div className="flex gap-2">
          {c.state === 'off' && (
            <Btn
              variant="primary"
              size="sm"
              // intentional fixed color: icon must read dark on the always-bright neon button
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
              // intentional fixed color: icon must read dark on the always-bright neon button
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
      <div className="flex flex-col gap-[22px] px-6 py-5">
        {c.state === 'err' && (
          <div className="flex gap-[10px] rounded-r6 border border-oxblood/30 bg-oxblood/10 p-3">
            <Lucide name="alert-triangle" size={14} color="var(--oxblood)" />
            <div className="flex-1">
              <div className="text-12 font-medium text-oxblood">oauth token expired</div>
              <div className="mt-[2px] text-11 leading-[1.4] text-ink-1">
                github stopped accepting our token 2 days ago. one click and it&rsquo;s quiet again.
              </div>
            </div>
          </div>
        )}

        <DetailBlock label="indexed">
          <div className="grid grid-cols-2 gap-[10px]">
            <Stat
              label="items"
              value={c.state === 'off' ? '—' : c.count.toLocaleString()}
              delta={c.throughput}
            />
            <Stat label="last sync" value={c.last} delta="auto · every 5m" />
          </div>
        </DetailBlock>

        <DetailBlock label="what ghostbrain pulls">
          <div className="flex flex-wrap gap-[6px]">
            {c.pulls.map((p) => (
              <Pill key={p} tone="fog">
                {p}
              </Pill>
            ))}
          </div>
        </DetailBlock>

        <DetailBlock label="oauth scopes">
          <div className="flex flex-col gap-[6px]">
            {c.scopes.map((s) => (
              <div
                key={s}
                className="flex items-center gap-2 font-mono text-11 text-ink-1"
              >
                <Lucide name="check" size={12} color="var(--neon)" />
                <span>{s}</span>
              </div>
            ))}
          </div>
        </DetailBlock>

        <DetailBlock label="vault destination">
          <div className="flex items-center gap-[10px] rounded-r6 border border-hairline bg-paper px-3 py-[10px]">
            <Lucide name="folder" size={13} color="var(--ink-2)" />
            <span className="flex-1 font-mono text-11 text-ink-0">
              ~/brain/sources/{c.name}
            </span>
            <Lucide name="external-link" size={11} color="var(--ink-3)" />
          </div>
        </DetailBlock>

        <DetailBlock label="filters">
          <div className="flex flex-col gap-2">
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
            className="mt-2 self-start"
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
      <Eyebrow className="mb-2">{label}</Eyebrow>
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
    <div className="rounded-md border border-hairline bg-paper p-[14px]">
      <Eyebrow>{label}</Eyebrow>
      <div className="mt-1 font-display text-28 font-semibold leading-[1.1] tracking-tight-x text-ink-0">
        {value}
      </div>
      <div className="mt-[2px] font-mono text-10 text-ink-2">{delta}</div>
    </div>
  );
}
