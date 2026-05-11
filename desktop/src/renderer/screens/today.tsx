import { useEffect, useState } from 'react';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { Eyebrow } from '../components/Eyebrow';
import { Panel } from '../components/Panel';
import { TopBar } from '../components/TopBar';
import { AskPanel } from '../components/AskPanel';
import { useNavigation } from '../stores/navigation';
import { stub } from '../stores/toast';
import {
  useAgenda,
  useCaptures,
  useConnectors,
  useRecentActivity,
  useSuggestions,
  useVaultStats,
} from '../lib/api/hooks';
import type {
  ActivityRow,
  AgendaItem,
  CaptureSummary,
  Connector,
  Suggestion,
} from '../../shared/api-types';
import { SkeletonRows } from '../components/SkeletonRows';
import { PanelEmpty } from '../components/PanelEmpty';
import { PanelError } from '../components/PanelError';

export function TodayScreen() {
  const setActive = useNavigation((s) => s.setActive);
  const stats = useVaultStats();
  const agenda = useAgenda();
  const activity = useRecentActivity();
  const connectors = useConnectors();
  const captures = useCaptures({ limit: 3 });
  const suggestions = useSuggestions();
  const [askOpen, setAskOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setAskOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const upcomingCount =
    agenda.data?.filter((e) => e.status === 'upcoming').length ?? 0;
  const connectorsOn =
    connectors.data?.filter((c) => c.state === 'on').length ?? 0;
  const unreadCount =
    captures.data?.items.filter((c) => c.unread).length ?? 0;

  return (
    <div className="flex-1 overflow-y-auto bg-paper">
      <AskPanel open={askOpen} onClose={() => setAskOpen(false)} />
      <TopBar
        title="today"
        subtitle="thursday · may 8"
        right={
          <div className="flex gap-2">
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="search" size={14} />}
              onClick={() => setAskOpen(true)}
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
              <span className="text-neon-ink">ghostbrain caught</span>
              <br />
              {stats.data?.indexedCount ?? '…'} things.
            </h2>
            <p className="mb-[18px] mt-[14px] max-w-[46ch] text-14 leading-[1.5] text-ink-1">
              {connectors.data
                ? `${connectorsOn} connectors syncing.`
                : '…'}{' '}
              {agenda.data
                ? `${upcomingCount} meetings on your calendar today.`
                : ''}
            </p>
            <div className="flex gap-2">
              <Btn
                variant="primary"
                size="md"
                // intentional fixed color: icon must read dark on the always-bright neon button
                icon={<Lucide name="search" size={14} color="#0E0F12" />}
                onClick={() => setAskOpen(true)}
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
            <Stat
              label="captured"
              value={stats.data ? stats.data.indexedCount.toLocaleString() : '—'}
              delta={stats.data && stats.data.queuePending > 0 ? `${stats.data.queuePending} pending` : 'in inbox'}
              tone="neon"
            />
            <Stat
              label="meetings"
              value={agenda.data ? String(upcomingCount) : '—'}
              delta={agenda.data && upcomingCount > 0 ? 'today' : ''}
            />
            <Stat
              label="unread"
              value={captures.data ? String(unreadCount) : '—'}
              delta="last 6 hours"
              tone={unreadCount > 0 ? 'neon' : undefined}
            />
            <Stat
              label="vault size"
              value={stats.data ? stats.data.totalNotes.toLocaleString() : '—'}
              delta="notes"
            />
          </div>
        </div>

        {/* Two-column: agenda + activity */}
        <div className="grid grid-cols-2 gap-4">
          {/* Agenda */}
          <Panel
            title="agenda"
            subtitle={
              agenda.data ? `${agenda.data.length} events · today` : '…'
            }
            action={
              <Btn
                variant="ghost"
                size="sm"
                iconRight={<Lucide name="arrow-right" size={12} />}
                onClick={() => setActive('meetings')}
              >
                calendar
              </Btn>
            }
          >
            {agenda.isLoading && <SkeletonRows count={3} />}
            {agenda.isError && (
              <PanelError
                message={
                  agenda.error instanceof Error
                    ? agenda.error.message
                    : 'failed to load agenda'
                }
                onRetry={() => agenda.refetch()}
              />
            )}
            {agenda.data && agenda.data.length === 0 && (
              <PanelEmpty icon="calendar" message="no events today" />
            )}
            {agenda.data?.map((item, i) => (
              <AgendaItemRow
                key={item.id}
                time={item.time}
                dur={item.duration}
                title={item.title}
                people={item.with}
                status={item.status}
                cta={
                  item.status === 'recorded' ? (
                    <Pill tone="moss">
                      <Lucide name="check" size={9} /> recorded
                    </Pill>
                  ) : item.status === 'upcoming' && i === 0 ? (
                    <Btn
                      variant="primary"
                      size="sm"
                      // intentional fixed color: icon must read dark on the always-bright neon button
                      icon={<Lucide name="mic" size={12} color="#0E0F12" />}
                      onClick={() => setActive('meetings')}
                    >
                      record
                    </Btn>
                  ) : (
                    <Btn
                      variant="ghost"
                      size="sm"
                      icon={<Lucide name="more-horizontal" size={12} />}
                      onClick={() => stub(3)}
                    />
                  )
                }
              />
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
            {activity.isLoading && <SkeletonRows count={4} />}
            {activity.isError && (
              <PanelError
                message={
                  activity.error instanceof Error
                    ? activity.error.message
                    : 'failed to load activity'
                }
                onRetry={() => activity.refetch()}
              />
            )}
            {activity.data && activity.data.length === 0 && (
              <PanelEmpty
                icon="activity"
                message="nothing in the last 4 hours"
              />
            )}
            {activity.data && (
              <ActivityList items={activity.data} />
            )}
          </Panel>
        </div>

        {/* Connector pulse strip */}
        <Panel
          title="connectors"
          subtitle={
            connectors.data
              ? `${connectorsOn} of ${connectors.data.length} connected`
              : '…'
          }
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
          {connectors.isLoading && <SkeletonRows count={1} height={64} />}
          {connectors.isError && (
            <PanelError
              message={
                connectors.error instanceof Error
                  ? connectors.error.message
                  : 'failed to load connectors'
              }
              onRetry={() => connectors.refetch()}
            />
          )}
          {connectors.data && connectors.data.length === 0 && (
            <PanelEmpty icon="plug" message="no connectors configured" />
          )}
          {connectors.data && connectors.data.length > 0 && (
            <div className="grid grid-cols-7 gap-2">
              {connectors.data.slice(0, 7).map((c) => (
                <ConnectorPulse
                  key={c.id}
                  id={c.id}
                  name={c.displayName}
                  state={c.state}
                  count={c.state === 'off' ? '—' : c.count.toLocaleString()}
                />
              ))}
            </div>
          )}
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
            {captures.isLoading && <SkeletonRows count={3} />}
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
              <PanelEmpty icon="inbox" message="nothing caught lately" />
            )}
            {captures.data?.items.map((c) => (
              <CaptureItem
                key={c.id}
                source={c.source}
                title={c.title}
                snippet={c.snippet}
                from={c.from}
              />
            ))}
          </Panel>

          <Panel title="suggested by ghostbrain" subtitle="quiet hunches">
            {suggestions.isLoading && <SkeletonRows count={2} />}
            {suggestions.isError && (
              <PanelError
                message={
                  suggestions.error instanceof Error
                    ? suggestions.error.message
                    : 'failed to load suggestions'
                }
                onRetry={() => suggestions.refetch()}
              />
            )}
            {suggestions.data && suggestions.data.length === 0 && (
              <PanelEmpty
                icon="sparkles"
                message="all caught up — no suggestions"
              />
            )}
            {suggestions.data?.map((s) => (
              <SuggestionCard
                key={s.id}
                icon={s.icon}
                title={s.title}
                body={s.body}
                accent={s.accent}
              />
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
          tone === 'neon' ? 'text-neon-ink' : 'text-ink-0'
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

interface AgendaItemRowProps {
  time: string;
  dur: string;
  title: string;
  people: AgendaItem['with'];
  status: AgendaItem['status'];
  cta?: React.ReactNode;
}

function AgendaItemRow({ time, dur, title, people, status, cta }: AgendaItemRowProps) {
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

interface ActivityRowCompProps {
  source: ActivityRow['source'];
  verb: ActivityRow['verb'];
  subject: ActivityRow['subject'];
  time: string;
}

function ActivityRowComp({ source, verb, subject, time }: ActivityRowCompProps) {
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

const ACTIVITY_INITIAL_LIMIT = 10;

function ActivityList({ items }: { items: ActivityRow[] }) {
  const [expanded, setExpanded] = useState(false);
  if (items.length === 0) {
    return <PanelEmpty icon="activity" message="nothing in the last 4 hours" />;
  }
  const visible = expanded ? items : items.slice(0, ACTIVITY_INITIAL_LIMIT);
  const hiddenCount = items.length - visible.length;
  return (
    <>
      {visible.map((row) => (
        <ActivityRowComp
          key={row.id}
          source={row.source}
          verb={row.verb}
          subject={row.subject}
          time={row.atRelative}
        />
      ))}
      {hiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-1 w-full rounded-sm px-[6px] py-2 text-center font-mono text-10 text-ink-2 hover:bg-paper"
        >
          view {hiddenCount} more
        </button>
      )}
      {expanded && items.length > ACTIVITY_INITIAL_LIMIT && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="mt-1 w-full rounded-sm px-[6px] py-2 text-center font-mono text-10 text-ink-3 hover:bg-paper"
        >
          collapse
        </button>
      )}
    </>
  );
}

interface ConnectorPulseProps {
  id: Connector['id'];
  name: string;
  state: Connector['state'];
  count: string;
}

function ConnectorPulse({ id, name, state, count }: ConnectorPulseProps) {
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
          src={`/assets/connectors/${id}.svg`}
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

interface CaptureItemProps {
  source: CaptureSummary['source'];
  title: CaptureSummary['title'];
  snippet: CaptureSummary['snippet'];
  from: CaptureSummary['from'];
}

function CaptureItem({ source, title, snippet, from }: CaptureItemProps) {
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

interface SuggestionCardProps {
  icon: Suggestion['icon'];
  title: Suggestion['title'];
  body: Suggestion['body'];
  accent?: Suggestion['accent'];
}

function SuggestionCard({ icon, title, body, accent }: SuggestionCardProps) {
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
