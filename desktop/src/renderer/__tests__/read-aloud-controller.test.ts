import { describe, expect, it } from 'vitest';
import { ReadAloudController, type ReadAloudStatus } from '../lib/read-aloud/controller';
import type { SpeechSegment } from '../lib/read-aloud/segments';
import { FakeSynth, FakeUtterance, end, fail, fakeVoice } from './helpers/fake-speech';

const SEGS: SpeechSegment[] = [
  { from: 1, to: 5, text: 'One.' },
  { from: 6, to: 10, text: 'Two.' },
  { from: 11, to: 17, text: 'Three.' },
];
const OPTS = { voice: null, rate: 1 };

function setup(synth = new FakeSynth()) {
  const highlights: Array<SpeechSegment | null> = [];
  const statuses: ReadAloudStatus[] = [];
  const errors: string[] = [];
  const ctrl = new ReadAloudController(
    synth,
    (t) => new FakeUtterance(t) as unknown as SpeechSynthesisUtterance,
    {
      onHighlight: (s) => highlights.push(s),
      onStatus: (s) => statuses.push(s),
      onError: (m) => errors.push(m),
    },
  );
  return { synth, ctrl, highlights, statuses, errors };
}

describe('ReadAloudController', () => {
  it('speaks from the start index, one utterance per sentence, highlighting each', () => {
    const { synth, ctrl, highlights, statuses } = setup();
    ctrl.start(SEGS, 1, OPTS);
    expect(synth.texts()).toEqual(['Two.']);
    expect(highlights).toEqual([SEGS[1]]);
    expect(statuses).toEqual(['playing']);
    end(synth.last);
    expect(synth.texts()).toEqual(['Two.', 'Three.']);
    expect(highlights.at(-1)).toEqual(SEGS[2]);
  });

  it('finishing the last sentence goes idle and clears the highlight', () => {
    const { synth, ctrl, highlights, statuses } = setup();
    ctrl.start(SEGS, 2, OPTS);
    end(synth.last);
    expect(ctrl.status).toBe('idle');
    expect(highlights.at(-1)).toBeNull();
    expect(statuses).toEqual(['playing', 'idle']);
  });

  it('applies voice and rate to every utterance', () => {
    const { synth, ctrl } = setup();
    const daniel = fakeVoice('Daniel', 'en-GB');
    ctrl.start(SEGS, 0, { voice: daniel, rate: 1.5 });
    end(synth.last);
    for (const u of synth.spoken) {
      expect(u.voice).toBe(daniel);
      expect(u.lang).toBe('en-GB');
      expect(u.rate).toBe(1.5);
    }
  });

  it('pause cancels and keeps the highlight; resume restarts the same sentence', () => {
    const { synth, ctrl, highlights } = setup();
    ctrl.start(SEGS, 0, OPTS);
    ctrl.pause();
    expect(synth.cancel).toHaveBeenCalled();
    expect(ctrl.status).toBe('paused');
    expect(highlights.at(-1)).toEqual(SEGS[0]);
    ctrl.resume();
    expect(synth.texts()).toEqual(['One.', 'One.']);
    expect(ctrl.status).toBe('playing');
  });

  it('ignores a late end/error from a paused or stopped utterance', () => {
    const { synth, ctrl, errors } = setup();
    ctrl.start(SEGS, 0, OPTS);
    const first = synth.last;
    ctrl.pause();
    fail(first, 'interrupted');
    end(first);
    expect(synth.spoken).toHaveLength(1);
    expect(ctrl.status).toBe('paused');

    ctrl.resume();
    const second = synth.last;
    ctrl.stop();
    fail(second, 'canceled');
    end(second);
    expect(synth.spoken).toHaveLength(2);
    expect(ctrl.status).toBe('idle');
    expect(errors).toEqual([]);
  });

  it('a new start supersedes the old run', () => {
    const { synth, ctrl } = setup();
    ctrl.start(SEGS, 0, OPTS);
    const old = synth.last;
    ctrl.start(SEGS, 2, OPTS);
    end(old);
    expect(synth.texts()).toEqual(['One.', 'Three.']);
  });

  it('stop cancels, clears the highlight and goes idle', () => {
    const { synth, ctrl, highlights } = setup();
    ctrl.start(SEGS, 0, OPTS);
    ctrl.stop();
    expect(synth.cancel).toHaveBeenCalled();
    expect(highlights.at(-1)).toBeNull();
    expect(ctrl.status).toBe('idle');
    expect(ctrl.currentSegment).toBeNull();
  });

  it('an engine failure stops and reports the error', () => {
    const { synth, ctrl, errors, highlights } = setup();
    ctrl.start(SEGS, 0, OPTS);
    fail(synth.last, 'synthesis-unavailable');
    expect(errors).toEqual(['synthesis-unavailable']);
    expect(ctrl.status).toBe('idle');
    expect(highlights.at(-1)).toBeNull();
  });

  it('empty segments stay idle and speak nothing', () => {
    const { synth, ctrl, statuses } = setup();
    ctrl.start([], 0, OPTS);
    expect(synth.spoken).toHaveLength(0);
    expect(statuses).toEqual([]);
  });

  it('clamps an out-of-range start index to the last sentence', () => {
    const { synth, ctrl } = setup();
    ctrl.start(SEGS, 9, OPTS);
    expect(synth.texts()).toEqual(['Three.']);
  });

  it('mapPositions shifts the queued ranges', () => {
    const { ctrl } = setup();
    ctrl.start(SEGS, 0, OPTS);
    ctrl.mapPositions((p) => p + 3);
    expect(ctrl.currentSegment).toEqual({ from: 4, to: 8, text: 'One.' });
  });

  it('pause and resume are no-ops in the wrong state', () => {
    const { synth, ctrl } = setup();
    ctrl.pause();
    ctrl.resume();
    expect(synth.spoken).toHaveLength(0);
    expect(ctrl.status).toBe('idle');
  });
  it('starting a second controller on the same engine halts the first', () => {
    const a = setup();
    const b = setup(a.synth);
    a.ctrl.start(SEGS, 0, OPTS);
    const aUtterance = a.synth.last;
    b.ctrl.start(SEGS, 1, OPTS);
    expect(a.ctrl.status).toBe('idle');
    expect(a.highlights.at(-1)).toBeNull();
    expect(a.statuses).toEqual(['playing', 'idle']);
    // The shared engine's late events for A's cut-off utterance never revive A.
    fail(aUtterance, 'interrupted');
    end(aUtterance);
    expect(a.ctrl.status).toBe('idle');
    expect(a.errors).toEqual([]);
    end(a.synth.last);
    expect(a.synth.texts()).toEqual(['One.', 'Two.', 'Three.']);
    expect(b.ctrl.status).toBe('playing');
  });

  it('resuming a paused controller halts the other active one', () => {
    const a = setup();
    const b = setup(a.synth);
    a.ctrl.start(SEGS, 0, OPTS);
    a.ctrl.pause();
    b.ctrl.start(SEGS, 2, OPTS);
    expect(a.ctrl.status).toBe('idle');
    a.ctrl.resume();
    expect(a.synth.texts()).toEqual(['One.', 'Three.']);
    b.ctrl.start(SEGS, 1, OPTS);
    a.ctrl.start(SEGS, 0, OPTS);
    expect(b.ctrl.status).toBe('idle');
    expect(b.highlights.at(-1)).toBeNull();
  });

  it('stopping an idle controller leaves another controller speaking', () => {
    const a = setup();
    const b = setup(a.synth);
    a.ctrl.start(SEGS, 0, OPTS);
    a.synth.cancel.mockClear();
    b.ctrl.stop();
    expect(a.synth.cancel).not.toHaveBeenCalled();
    expect(b.statuses).toEqual([]);
    expect(b.highlights).toEqual([]);
    expect(a.ctrl.status).toBe('playing');
    end(a.synth.last);
    expect(a.synth.texts()).toEqual(['One.', 'Two.']);
    expect(a.ctrl.status).toBe('playing');
  });

  it('an outside cancel of the current utterance goes idle quietly', () => {
    const { synth, ctrl, highlights, errors } = setup();
    ctrl.start(SEGS, 0, OPTS);
    fail(synth.last, 'interrupted');
    expect(ctrl.status).toBe('idle');
    expect(highlights.at(-1)).toBeNull();
    expect(errors).toEqual([]);
    end(synth.last);
    expect(synth.spoken).toHaveLength(1);
  });
});
