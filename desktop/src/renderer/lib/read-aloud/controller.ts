import type { SpeechSegment } from './segments';

export type ReadAloudStatus = 'idle' | 'playing' | 'paused';

/** The two calls we need from window.speechSynthesis (fakeable in tests). */
export interface SpeechEngine {
  speak(u: SpeechSynthesisUtterance): void;
  cancel(): void;
}

export interface SpeakOptions {
  voice: SpeechSynthesisVoice | null;
  rate: number;
}

export interface ReadAloudCallbacks {
  onHighlight(segment: SpeechSegment | null): void;
  onStatus(status: ReadAloudStatus): void;
  onError(message: string): void;
}

/** Error codes that mean "we cancelled it", not "the engine failed". */
const BENIGN = new Set(['interrupted', 'canceled']);

/** speechSynthesis is one global queue, but several editors can each own a
 * controller (jots + the NoteView overlay). Only one may speak at a time. */
const slot: { active: ReadAloudController | null } = { active: null };

/** Speaks segments one utterance per sentence. Every speak bumps `gen`, and
 * every event handler checks it, so the async end/error that Chromium fires
 * for a cancelled utterance can never advance or restart playback. Pause =
 * cancel + remember the sentence; resume re-speaks it from its start. */
export class ReadAloudController {
  private segments: SpeechSegment[] = [];
  private index = 0;
  private gen = 0;
  private opts: SpeakOptions = { voice: null, rate: 1 };
  private _status: ReadAloudStatus = 'idle';
  // Chromium can drop events of an utterance nothing references any more.
  private current: SpeechSynthesisUtterance | null = null;

  constructor(
    private readonly engine: SpeechEngine,
    private readonly makeUtterance: (text: string) => SpeechSynthesisUtterance,
    private readonly cb: ReadAloudCallbacks,
  ) {}

  get status(): ReadAloudStatus {
    return this._status;
  }

  get currentSegment(): SpeechSegment | null {
    return this._status === 'idle' ? null : (this.segments[this.index] ?? null);
  }

  start(segments: SpeechSegment[], startIndex: number, opts: SpeakOptions): void {
    this.gen++;
    this.engine.cancel();
    if (segments.length === 0) {
      this.reset();
      return;
    }
    this.segments = segments.slice();
    this.opts = opts;
    this.index = Math.min(Math.max(0, startIndex), segments.length - 1);
    this.speakCurrent();
  }

  pause(): void {
    if (this._status !== 'playing') return;
    this.gen++;
    this.engine.cancel();
    this.current = null;
    this.setStatus('paused');
  }

  resume(): void {
    if (this._status !== 'paused') return;
    this.speakCurrent();
  }

  /** No-op when idle: the engine is shared, so an idle controller (e.g. an
   * unmounting editor that never read) must not cancel another one's speech. */
  stop(): void {
    if (this._status === 'idle') return;
    this.gen++;
    this.engine.cancel();
    this.reset();
  }

  /** Keep queued ranges valid while the user edits during playback. */
  mapPositions(map: (pos: number, assoc?: number) => number): void {
    this.segments = this.segments.map((s) => {
      const from = map(s.from, 1);
      return { ...s, from, to: Math.max(from, map(s.to, -1)) };
    });
  }

  /** Another controller took the engine (and already cancelled it): drop
   * this run without cancelling again. */
  private halt(): void {
    this.gen++;
    this.reset();
  }

  private speakCurrent(): void {
    const seg = this.segments[this.index];
    if (!seg) {
      this.reset();
      return;
    }
    if (slot.active && slot.active !== this) slot.active.halt();
    slot.active = this;
    const gen = ++this.gen;
    const u = this.makeUtterance(seg.text);
    if (this.opts.voice) {
      u.voice = this.opts.voice;
      u.lang = this.opts.voice.lang;
    }
    u.rate = this.opts.rate;
    u.onend = () => {
      if (gen !== this.gen) return;
      this.index++;
      this.speakCurrent();
    };
    u.onerror = (e: SpeechSynthesisErrorEvent) => {
      if (gen !== this.gen) return;
      this.gen++;
      // Every internal cancel bumps gen first, so a benign error on the
      // current gen is an outside cancel: go idle quietly.
      if (BENIGN.has(e.error)) {
        this.reset();
        return;
      }
      this.engine.cancel();
      this.reset();
      this.cb.onError(e.error);
    };
    this.current = u;
    this.cb.onHighlight(seg);
    this.setStatus('playing');
    this.engine.speak(u);
  }

  private reset(): void {
    const wasActive = this._status !== 'idle';
    this.segments = [];
    this.index = 0;
    this.current = null;
    if (slot.active === this) slot.active = null;
    if (wasActive) this.cb.onHighlight(null);
    this.setStatus('idle');
  }

  private setStatus(s: ReadAloudStatus): void {
    if (s === this._status) return;
    this._status = s;
    this.cb.onStatus(s);
  }
}
