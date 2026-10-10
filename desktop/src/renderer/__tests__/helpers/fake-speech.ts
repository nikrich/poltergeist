import { vi } from 'vitest';

/** jsdom has no speechSynthesis — a minimal, inspectable stand-in. */
export class FakeUtterance {
  text: string;
  voice: SpeechSynthesisVoice | null = null;
  rate = 1;
  lang = '';
  onstart: ((ev: unknown) => void) | null = null;
  onend: ((ev: unknown) => void) | null = null;
  onerror: ((ev: { error: string }) => void) | null = null;
  constructor(text: string) {
    this.text = text;
  }
}

export class FakeSynth {
  spoken: FakeUtterance[] = [];
  cancel = vi.fn();
  voices: SpeechSynthesisVoice[] = [];
  private listeners = new Set<() => void>();

  speak(u: SpeechSynthesisUtterance): void {
    this.spoken.push(u as unknown as FakeUtterance);
  }
  getVoices(): SpeechSynthesisVoice[] {
    return this.voices;
  }
  addEventListener(type: string, fn: () => void): void {
    if (type === 'voiceschanged') this.listeners.add(fn);
  }
  removeEventListener(type: string, fn: () => void): void {
    if (type === 'voiceschanged') this.listeners.delete(fn);
  }
  /** Simulates the OS finishing its async voice load. */
  setVoices(v: SpeechSynthesisVoice[]): void {
    this.voices = v;
    this.listeners.forEach((fn) => fn());
  }
  get last(): FakeUtterance | undefined {
    return this.spoken[this.spoken.length - 1];
  }
  texts(): string[] {
    return this.spoken.map((u) => u.text);
  }
}

export function end(u: FakeUtterance | undefined): void {
  u?.onend?.({});
}

export function fail(u: FakeUtterance | undefined, error: string): void {
  u?.onerror?.({ error });
}

export function fakeVoice(
  name: string,
  lang: string,
  extra: Partial<SpeechSynthesisVoice> = {},
): SpeechSynthesisVoice {
  return {
    name,
    lang,
    voiceURI: `${name}-uri`,
    localService: true,
    default: false,
    ...extra,
  } as SpeechSynthesisVoice;
}

const targets = (): Array<Record<string, unknown>> => [
  globalThis as unknown as Record<string, unknown>,
  window as unknown as Record<string, unknown>,
];

export function installFakeSpeech(): FakeSynth {
  const synth = new FakeSynth();
  for (const t of targets()) {
    t.speechSynthesis = synth;
    t.SpeechSynthesisUtterance = FakeUtterance;
  }
  return synth;
}

export function uninstallFakeSpeech(): void {
  for (const t of targets()) {
    delete t.speechSynthesis;
    delete t.SpeechSynthesisUtterance;
  }
}
