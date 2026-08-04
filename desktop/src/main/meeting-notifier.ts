import { BrowserWindow, Notification, app } from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import type { AgendaItem } from '../shared/api-types';
import type { Sidecar } from './sidecar';

const LEAD_MINUTES = 15;

export function shouldFireNow(
  event: AgendaItem,
  now: Date,
  notified: ReadonlySet<string>,
): boolean {
  if (event.status !== 'upcoming') return false;
  if (notified.has(event.id)) return false;
  const match = event.time.match(/^(\d{2}):(\d{2})$/);
  if (!match) return false;
  const start = new Date(now);
  start.setHours(Number(match[1]), Number(match[2]), 0, 0);
  const fireAt = start.getTime() - LEAD_MINUTES * 60_000;
  // Window: [fireAt, start). If we missed fireAt by ≤15 min but the meeting
  // hasn't started yet, fire (covers an app that booted just before the
  // meeting starts).
  return now.getTime() >= fireAt && now.getTime() < start.getTime();
}

const POLL_INTERVAL_MS = 60_000;
const NOTIFIED_PRUNE_AFTER_MS = 24 * 60 * 60 * 1000;

// InstallOpts accepts a Sidecar instance so we can replicate the same
// Authorization: Bearer <token> header used by api-forwarder.ts. A raw URL
// string would result in 401 responses because the sidecar requires the
// bearer token on every request.
interface InstallOpts {
  sidecar: Sidecar;
}

export interface MeetingNotifierController {
  destroy: () => void;
}

interface NotifiedRecord {
  /** event id → epoch ms when it was notified */
  [eventId: string]: number;
}

function notifiedFilePath(): string {
  return path.join(app.getPath('userData'), 'meeting-notified.json');
}

function loadNotified(): NotifiedRecord {
  try {
    const raw = fs.readFileSync(notifiedFilePath(), 'utf-8');
    const parsed = JSON.parse(raw) as NotifiedRecord;
    const now = Date.now();
    const fresh: NotifiedRecord = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof v === 'number' && now - v < NOTIFIED_PRUNE_AFTER_MS) {
        fresh[k] = v;
      }
    }
    return fresh;
  } catch {
    return {};
  }
}

function saveNotified(record: NotifiedRecord): void {
  try {
    fs.writeFileSync(notifiedFilePath(), JSON.stringify(record), 'utf-8');
  } catch (e) {
    console.warn('[meeting-notifier] could not save notified-set:', e);
  }
}

function fireNotification(event: AgendaItem): void {
  if (!Notification.isSupported()) return;
  const notification = new Notification({
    title: `${event.title} in 15 min`,
    body: event.with.length
      ? `with ${event.with.slice(0, 3).join(', ')}`
      : '',
    silent: false,
  });
  notification.on('click', () => {
    for (const win of BrowserWindow.getAllWindows()) {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
      win.webContents.send('gb:meetings:openPrep', event.id);
    }
  });
  notification.show();
}

export function installMeetingNotifier(opts: InstallOpts): MeetingNotifierController {
  let notified = loadNotified();
  let timer: NodeJS.Timeout | null = null;

  async function tick(): Promise<void> {
    try {
      // Replicate the same auth pattern as api-forwarder.ts: read port and
      // token from the live Sidecar instance. If the sidecar is not yet ready,
      // getInfo() returns null and we skip this tick.
      const info = opts.sidecar.getInfo();
      if (!info) return;
      const res = await fetch(`http://127.0.0.1:${info.port}/v1/agenda`, {
        headers: {
          Authorization: `Bearer ${info.token}`,
        },
        signal: AbortSignal.timeout(10_000),
      });
      if (!res.ok) return;
      const items = (await res.json()) as AgendaItem[];
      const now = new Date();
      const ids = new Set(Object.keys(notified));
      for (const event of items) {
        if (shouldFireNow(event, now, ids)) {
          fireNotification(event);
          notified[event.id] = Date.now();
          ids.add(event.id);
        }
      }
      saveNotified(notified);
    } catch (e) {
      // Sidecar may be booting or down — try again next tick.
      console.warn('[meeting-notifier] poll failed:', e);
    }
  }

  // Fire one immediately so a freshly-launched app catches an imminent meeting,
  // then schedule the recurring poll.
  void tick();
  timer = setInterval(() => void tick(), POLL_INTERVAL_MS);

  return {
    destroy() {
      if (timer !== null) clearInterval(timer);
      timer = null;
    },
  };
}
