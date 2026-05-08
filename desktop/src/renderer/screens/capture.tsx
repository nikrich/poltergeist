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

function chipClass(active: boolean): string {
  return `cursor-pointer rounded-sm border px-[10px] py-1 font-mono text-11 ${
    active
      ? 'border-neon/30 bg-neon/15 text-neon-ink'
      : 'border-hairline-2 bg-transparent text-ink-1'
  }`;
}

export function CaptureScreen() {
  const [selected, setSelected] = useState<number>(1);
  const [filter, setFilter] = useState<string>('all');
  const item = CAPTURE_ITEMS.find((c) => c.id === selected);
  const filtered = CAPTURE_ITEMS.filter((c) => filter === 'all' || c.source === filter);
  const unread = CAPTURE_ITEMS.filter((c) => c.unread).length;

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar
        title="capture"
        subtitle={`${unread} unread · ${CAPTURE_ITEMS.length} today`}
        right={
          <div className="flex gap-2">
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
      <div className="flex flex-shrink-0 items-center gap-[6px] border-b border-hairline px-6 py-3">
        <button onClick={() => setFilter('all')} className={chipClass(filter === 'all')}>
          all
        </button>
        {SOURCES.map((s) => (
          <button key={s} onClick={() => setFilter(s)} className={chipClass(filter === s)}>
            <img
              src={`/assets/connectors/${s}.svg`}
              alt=""
              className="mr-1 inline-block h-[11px] w-[11px] align-[-1px]"
            />
            {s}
          </button>
        ))}
      </div>

      <div className="grid flex-1 grid-cols-[1fr_480px] overflow-hidden">
        {/* List */}
        <div className="overflow-y-auto px-2 py-3">
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
    <button
      type="button"
      onClick={onClick}
      className={`mb-[2px] grid w-full cursor-pointer grid-cols-[20px_14px_1fr_auto] items-center gap-[10px] rounded-r6 border-l-2 px-[14px] py-[10px] text-left ${
        selected ? 'border-l-neon bg-vellum' : 'border-l-transparent bg-transparent'
      }`}
    >
      <span
        className={`h-[6px] w-[6px] justify-self-center rounded-full ${
          c.unread ? 'bg-neon' : 'bg-transparent'
        }`}
      />
      <img src={`/assets/connectors/${c.source}.svg`} alt="" className="h-[13px] w-[13px]" />
      <div className="min-w-0">
        <div className="flex items-baseline gap-2">
          <span
            className={`overflow-hidden text-ellipsis whitespace-nowrap text-13 text-ink-0 ${
              c.unread ? 'font-medium' : 'font-normal'
            }`}
          >
            {c.title}
          </span>
          <span className="whitespace-nowrap font-mono text-9 text-ink-3">{c.from}</span>
        </div>
        <div className="mt-[2px] overflow-hidden text-ellipsis whitespace-nowrap font-display text-11 italic text-ink-2">
          {c.snippet}
        </div>
      </div>
      <div className="flex gap-1">
        {c.tags.slice(0, 1).map((t) => (
          <Pill key={t} tone="outline">
            {t}
          </Pill>
        ))}
      </div>
    </button>
  );
}

interface CaptureDetailProps {
  c: CaptureRecord;
}

function CaptureDetail({ c }: CaptureDetailProps) {
  return (
    <aside className="overflow-y-auto border-l border-hairline bg-vellum p-6">
      <div className="mb-[14px] flex items-center gap-[10px]">
        <img src={`/assets/connectors/${c.source}.svg`} alt="" className="h-[18px] w-[18px]" />
        <span className="font-mono text-11 text-ink-2">
          {c.source} · {c.from}
        </span>
        <div className="flex-1" />
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
      <h3 className="m-0 font-display text-22 font-semibold leading-[1.15] tracking-tight-x text-ink-0">
        {c.title}
      </h3>
      <p className="mt-[14px] font-display text-16 italic leading-[1.55] text-ink-0">
        &ldquo;{c.snippet}&rdquo;
      </p>

      <div className="mt-6">
        <Eyebrow className="mb-[10px]">ghostbrain extracted</Eyebrow>
        <div className="flex flex-col gap-[10px] rounded-md border border-hairline bg-paper p-[14px]">
          <Catch icon="check-square" text="action: ping mira about thursday" />
          <Catch icon="link" text="ref: design crit · onboarding v3" />
          <Catch icon="user" text="people: theo, mira" />
        </div>
      </div>

      <div className="mt-5">
        <Eyebrow className="mb-[10px]">destination</Eyebrow>
        <div className="flex items-center gap-[10px] rounded-r6 border border-hairline bg-paper px-3 py-[10px]">
          <Lucide name="folder" size={13} color="var(--ink-2)" />
          <span className="flex-1 font-mono text-11 text-ink-0">~/brain/Daily/2026-05-08.md</span>
        </div>
      </div>

      <div className="mt-6 flex gap-2">
        <Btn
          variant="primary"
          size="sm"
          // intentional fixed color: icon must read dark on the always-bright neon button
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
