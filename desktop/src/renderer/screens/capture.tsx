import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import type { Capture, CaptureSummary } from '../../shared/api-types';
import { useCapture, useCaptures, useConnectors } from '../lib/api/hooks';
import { SkeletonRows } from '../components/SkeletonRows';
import { PanelEmpty } from '../components/PanelEmpty';
import { PanelError } from '../components/PanelError';
import { stub } from '../stores/toast';

function chipClass(active: boolean): string {
  return `cursor-pointer rounded-sm border px-[10px] py-1 font-mono text-11 ${
    active
      ? 'border-neon/30 bg-neon/15 text-neon-ink'
      : 'border-hairline-2 bg-transparent text-ink-1'
  }`;
}

// Capture `source` is hyphenated (`claude-code`); connector ids and SVG asset
// filenames use underscores (`claude_code`). Normalize both directions.
function sourceFromId(id: string): string {
  return id.replace(/_/g, '-');
}
function assetIdFromSource(source: string): string {
  return source.replace(/-/g, '_');
}

export function CaptureScreen() {
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>('all');
  const connectors = useConnectors();
  const captures = useCaptures({ source: filter === 'all' ? undefined : filter });
  const detail = useCapture(selected);

  const sources = useMemo(
    () =>
      (connectors.data ?? [])
        .filter((c) => c.state === 'on')
        .map((c) => ({ value: sourceFromId(c.id), asset: c.id, label: sourceFromId(c.id) })),
    [connectors.data],
  );

  // Default selection to first item once data arrives
  useEffect(() => {
    if (selected === null && captures.data && captures.data.items.length > 0) {
      setSelected(captures.data.items[0]!.id);
    }
  }, [captures.data, selected]);

  const unreadCount = captures.data?.items.filter((c) => c.unread).length ?? 0;
  const totalToday = captures.data?.total ?? 0;

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar
        title="capture"
        subtitle={captures.data ? `${unreadCount} unread · ${totalToday} today` : '…'}
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
        {sources.map((s) => (
          <button
            key={s.value}
            onClick={() => setFilter(s.value)}
            className={chipClass(filter === s.value)}
          >
            <img
              src={`/assets/connectors/${s.asset}.svg`}
              alt=""
              className="mr-1 inline-block h-[11px] w-[11px] align-[-1px]"
            />
            {s.label}
          </button>
        ))}
      </div>

      <div className="grid flex-1 grid-cols-[1fr_480px] overflow-hidden">
        {/* List */}
        <div className="overflow-y-auto px-2 py-3">
          {captures.isLoading && <SkeletonRows count={6} height={56} />}
          {captures.isError && (
            <PanelError
              message={
                captures.error instanceof Error
                  ? captures.error.message
                  : 'failed to load captures'
              }
              onRetry={() => captures.refetch()}
            />
          )}
          {captures.data && captures.data.items.length === 0 && (
            <PanelEmpty icon="inbox" message="nothing captured yet" />
          )}
          {captures.data?.items.map((c) => (
            <CaptureRow
              key={c.id}
              c={c}
              selected={selected === c.id}
              onClick={() => setSelected(c.id)}
            />
          ))}
        </div>

        {/* Detail */}
        {detail.isLoading && (
          <aside className="overflow-y-auto border-l border-hairline bg-vellum p-6">
            <SkeletonRows count={4} />
          </aside>
        )}
        {detail.isError && (
          <aside className="overflow-y-auto border-l border-hairline bg-vellum p-6">
            <PanelError
              message={
                detail.error instanceof Error ? detail.error.message : 'failed to load capture'
              }
              onRetry={() => detail.refetch()}
            />
          </aside>
        )}
        {detail.data && <CaptureDetail c={detail.data} />}
      </div>
    </div>
  );
}

interface CaptureRowProps {
  c: CaptureSummary;
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
      <img
        src={`/assets/connectors/${assetIdFromSource(c.source)}.svg`}
        alt=""
        className="h-[13px] w-[13px]"
      />
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
  c: Capture;
}

function CaptureDetail({ c }: CaptureDetailProps) {
  return (
    <aside className="overflow-y-auto border-l border-hairline bg-vellum p-6">
      <div className="mb-[14px] flex items-center gap-[10px]">
        <img
          src={`/assets/connectors/${assetIdFromSource(c.source)}.svg`}
          alt=""
          className="h-[18px] w-[18px]"
        />
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
      {c.body && (
        <article className="gb-prose mt-[14px] text-13 leading-[1.6] text-ink-0">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{c.body}</ReactMarkdown>
        </article>
      )}

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
