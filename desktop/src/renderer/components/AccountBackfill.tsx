import { useEffect, useRef, useState } from 'react';

import { Btn } from './Btn';
import { Lucide } from './Lucide';
import type {
  BackfillState,
  DriveBackfillEstimate,
  GmailBackfillEstimate,
} from '../../shared/api-types';
import { ApiError } from '../lib/api/client';
import {
  type BackfillAction,
  useAccountBackfill,
  useBackfillAction,
  useBackfillEstimate,
  useStartBackfill,
} from '../lib/api/hooks';
import { toast } from '../stores/toast';

/** Items per hour the scheduler gets through (25 items every 120 s), for both connectors. */
const PACE_PER_HOUR = 750;
const YEAR_OPTIONS = [1, 2, 3, 5] as const;
const DEFAULT_YEARS = 3;
const AUTH_ERROR = 'needs re-auth';
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const fmt = (n: number) => n.toLocaleString('en-US');

const paceText = (n: number) =>
  n < PACE_PER_HOUR
    ? 'under an hour at the current pace'
    : `roughly ${Math.ceil(n / PACE_PER_HOUR)} h or more`;

type BackfillEstimate = GmailBackfillEstimate | DriveBackfillEstimate;

interface ConnectorConfig {
  /** Blurb shown at the top of the backfill dialog. */
  blurb: string;
  /** Estimate line shown under the years selector, given the estimate response. */
  estimateLine: (data: BackfillEstimate) => string;
}

const CONNECTOR_CONFIG: Record<string, ConnectorConfig> = {
  gmail: {
    blurb:
      'Import past threads you took part in — sent by you, starred or important — ' +
      'skipping promotions. Runs in the background a small batch at a time.',
    estimateLine: (data) => {
      const n = (data as GmailBackfillEstimate).threads;
      return `~${fmt(n)} threads you took part in · ${paceText(n)}`;
    },
  },
  gdrive: {
    blurb:
      'Import past Docs, Sheets, PDFs and Word/Excel files you own or edited. Runs in the ' +
      'background a small batch at a time.',
    estimateLine: (data) => {
      const { files, capped } = data as DriveBackfillEstimate;
      return `~${fmt(files)}${capped ? '+' : ''} files you own or edited · ${paceText(files)}`;
    },
  },
};

/** Connector ids that support the backfill entry point + progress line. */
export const BACKFILL_CONNECTORS: ReadonlySet<string> = new Set(Object.keys(CONNECTOR_CONFIG));

/** 'YYYY-MM' → 'Mon YYYY'; anything unexpected is shown as-is. */
function monthLabel(cursor: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(cursor);
  const name = m ? MONTHS[Number(m[2]) - 1] : undefined;
  return m && name ? `${name} ${m[1]}` : cursor;
}

const errMessage = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

interface Props {
  connectorId: string;
  accountId: string;
  onReauth: (accountId: string) => void;
}

/** Backfill entry point + progress line for one account row (Gmail or Drive). */
export function AccountBackfill({ connectorId, accountId, onReauth }: Props) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const backfill = useAccountBackfill(connectorId, accountId);
  const action = useBackfillAction();

  // First load: don't flash the "backfill…" button before we know whether a
  // backfill is already running for this account.
  if (backfill.isPending) return null;

  // Guard against malformed payloads so an odd response never breaks the row.
  const state: BackfillState | null = backfill.data?.status ? backfill.data : null;

  const run = (a: BackfillAction) => {
    if (a === 'cancel' && state?.status !== 'done') {
      const ok = window.confirm(
        `Cancel the backfill for ${accountId}? Notes already imported are kept.`,
      );
      if (!ok) return;
    }
    action.mutate(
      { connectorId, accountId, action: a },
      { onError: (e) => toast.error(errMessage(e, `${accountId}: backfill ${a} failed`)) },
    );
  };

  if (state === null) {
    return (
      <>
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="history" size={12} />}
          className="self-start"
          ariaLabel={`backfill ${accountId}`}
          onClick={() => setDialogOpen(true)}
        >
          backfill…
        </Btn>
        {dialogOpen && (
          <BackfillDialog
            connectorId={connectorId}
            accountId={accountId}
            onClose={() => setDialogOpen(false)}
            onReauth={onReauth}
          />
        )}
      </>
    );
  }

  const btn = (a: BackfillAction, label: string, icon: string) => (
    <Btn
      variant="ghost"
      size="sm"
      icon={<Lucide name={icon} size={12} />}
      ariaLabel={`${a === 'cancel' && state.status === 'done' ? 'dismiss' : a} backfill for ${accountId}`}
      disabled={action.isPending}
      onClick={() => run(a)}
    >
      {label}
    </Btn>
  );

  let text: React.ReactNode;
  let buttons: React.ReactNode;
  if (state.status === 'running') {
    const updatedPart = state.updated !== undefined ? ` · ${fmt(state.updated)} updated` : '';
    const tooLargePart = state.tooLarge !== undefined ? ` · ${fmt(state.tooLarge)} too large` : '';
    text = (
      <>
        <span>
          {`backfilling · ${monthLabel(state.cursor)} · ${fmt(state.imported)} imported${updatedPart} · ${fmt(state.skipped)} already had · ${fmt(state.failed)} failed${tooLargePart}`}
        </span>
        {state.error && <span className="text-ink-3">{`retrying after ${state.error}`}</span>}
      </>
    );
    buttons = (
      <>
        {btn('pause', 'pause', 'pause')}
        {btn('cancel', 'cancel', 'x')}
      </>
    );
  } else if (state.status === 'paused') {
    text = (
      <span>
        {`backfill paused · ${monthLabel(state.cursor)} · ${fmt(state.imported)} imported`}
      </span>
    );
    buttons = (
      <>
        {btn('resume', 'resume', 'play')}
        {btn('cancel', 'cancel', 'x')}
      </>
    );
  } else if (state.status === 'error') {
    const needsAuth = state.error === AUTH_ERROR;
    text = (
      <span className="text-oxblood">
        {needsAuth
          ? `backfill paused · ${AUTH_ERROR}`
          : `backfill stopped · ${state.error ?? 'unknown error'}`}
      </span>
    );
    buttons = (
      <>
        {needsAuth && (
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="refresh-cw" size={12} />}
            ariaLabel={`reauthorize backfill for ${accountId}`}
            onClick={() => onReauth(accountId)}
          >
            reauthorize
          </Btn>
        )}
        {btn('resume', 'resume', 'play')}
        {btn('cancel', 'cancel', 'x')}
      </>
    );
  } else {
    text = <span>{`backfill complete · ${fmt(state.imported)} imported`}</span>;
    buttons = btn('cancel', 'dismiss', 'check');
  }

  return (
    <div
      data-testid={`backfill-${accountId}`}
      className="flex flex-wrap items-center gap-2 font-mono text-11 text-ink-2"
    >
      <Lucide name="history" size={12} />
      <div className="flex min-w-0 flex-1 flex-col">{text}</div>
      {buttons}
    </div>
  );
}

interface DialogProps {
  connectorId: string;
  accountId: string;
  onClose: () => void;
  onReauth: (accountId: string) => void;
}

function BackfillDialog({ connectorId, accountId, onClose, onReauth }: DialogProps) {
  const [years, setYears] = useState<number>(DEFAULT_YEARS);
  const [blocked, setBlocked] = useState<string | null>(null);
  // Only rendered for connectors in BACKFILL_CONNECTORS (the keys of
  // CONNECTOR_CONFIG). Should that ever not hold, show no blurb or estimate
  // text rather than another connector's.
  const config: ConnectorConfig | undefined = CONNECTOR_CONFIG[connectorId];
  const estimate = useBackfillEstimate<BackfillEstimate>(connectorId, accountId, years);
  const start = useStartBackfill();
  const dialogRef = useRef<HTMLDivElement>(null);

  // Move focus into the dialog on open; Escape dismisses it.
  useEffect(() => {
    dialogRef.current?.focus();
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // A 409 "needs re-auth" from the estimate means the account's token is
  // unusable: starting would only park the backfill there. Any other estimate
  // failure (e.g. a 409 asking to enable a Google API, a 503 when Drive is
  // busy) is shown as the estimate line and must not block starting.
  const needsReauth =
    estimate.isError &&
    estimate.error instanceof ApiError &&
    estimate.error.status === 409 &&
    estimate.error.message === AUTH_ERROR;

  const onStart = () =>
    start.mutate(
      { connectorId, accountId, years },
      {
        onSuccess: () => {
          toast.info(`${accountId}: backfill started`);
          onClose();
        },
        onError: (e) => {
          // 409: scheduler off — show the server's explanation instead of a start button.
          if (e instanceof ApiError && e.status === 409) setBlocked(e.message);
          else toast.error(errMessage(e, `${accountId}: backfill failed to start`));
        },
      },
    );

  let estimateLine: string;
  if (estimate.isPending) estimateLine = 'estimating…';
  else if (estimate.isError) estimateLine = errMessage(estimate.error, 'estimate unavailable');
  else estimateLine = config ? config.estimateLine(estimate.data) : '';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={`backfill ${accountId}`}
        tabIndex={-1}
        className="w-[420px] outline-none overflow-hidden rounded-lg border border-hairline-2 bg-vellum shadow-float"
      >
        <div className="flex items-center justify-between border-b border-hairline px-4 py-3">
          <span className="text-13 font-semibold text-ink-0">backfill {accountId}</span>
          <button
            type="button"
            aria-label="close"
            onClick={onClose}
            className="text-ink-3 hover:text-ink-1"
          >
            ✕
          </button>
        </div>
        <div className="flex flex-col gap-3 p-4">
          {config && <div className="text-12 text-ink-1">{config.blurb}</div>}
          <label className="flex items-center gap-2 text-12 text-ink-1">
            go back
            <select
              aria-label="years to backfill"
              value={years}
              onChange={(e) => setYears(Number(e.target.value))}
              className="rounded-r6 border border-hairline-2 bg-paper px-2 py-1 font-mono text-11 text-ink-0"
            >
              {YEAR_OPTIONS.map((y) => (
                <option key={y} value={y}>
                  {y === 1 ? '1 year' : `${y} years`}
                </option>
              ))}
            </select>
          </label>
          <div className="font-mono text-11 text-ink-2">{estimateLine}</div>
          {blocked !== null && <div className="text-12 text-oxblood">{blocked}</div>}
          <div className="flex justify-end gap-2">
            <Btn variant="secondary" size="sm" onClick={onClose}>
              close
            </Btn>
            {needsReauth ? (
              <Btn
                size="sm"
                icon={<Lucide name="refresh-cw" size={12} />}
                ariaLabel={`reauthorize ${accountId} for backfill`}
                onClick={() => {
                  onReauth(accountId);
                  onClose();
                }}
              >
                reauthorize
              </Btn>
            ) : (
              blocked === null && (
                <Btn size="sm" onClick={onStart} disabled={start.isPending}>
                  start backfill
                </Btn>
              )
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
