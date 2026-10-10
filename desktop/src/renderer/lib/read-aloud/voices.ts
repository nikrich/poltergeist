import { useEffect, useState } from 'react';
import type { NoteLanguage } from './language';

/** Web Speech runs in Chromium's browser process (platform TTS: AVSpeech /
 * NSSpeechSynthesizer on macOS, SAPI on Windows); the sandboxed renderer only
 * needs the API to exist. */
export function isSpeechSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'speechSynthesis' in window &&
    typeof window.SpeechSynthesisUtterance === 'function'
  );
}

/** macOS novelty/character voices (singing, robotic, croaking). Chromium even
 * flags Albert as the default voice, so they must never be offered or picked. */
const NOVELTY = new Set([
  'albert', 'bad news', 'bahh', 'bells', 'boing', 'bubbles', 'cellos', 'fred',
  'good news', 'grandma', 'grandpa', 'jester', 'junior', 'kathy', 'organ', 'ralph',
  'rocko', 'superstar', 'trinoids', 'whisper', 'wobble', 'zarvox',
]);

function baseName(v: SpeechSynthesisVoice): string {
  // "Eddy (English (United Kingdom))" → "eddy"; "Samantha (Premium)" → "samantha".
  return v.name.split(' (')[0]!.trim().toLowerCase();
}

function isNovelty(v: SpeechSynthesisVoice): boolean {
  return NOVELTY.has(baseName(v));
}

/** Offline voices only (the user approved OS voices, never a network TTS),
 * minus the novelty voices. */
export function localVoices(all: readonly SpeechSynthesisVoice[]): SpeechSynthesisVoice[] {
  return all
    .filter((v) => v.localService && !isNovelty(v))
    .sort((a, b) => a.lang.localeCompare(b.lang) || a.name.localeCompare(b.name));
}

/** Natural-sounding voices, best first. Tessa is South African English. */
const PREFERRED = ['tessa', 'samantha', 'daniel', 'karen', 'moira', 'rishi'];

function quality(v: SpeechSynthesisVoice): number {
  const premium = /\((premium|enhanced)\)/i.test(v.name) ? 0 : 100;
  const rank = PREFERRED.indexOf(baseName(v));
  return premium + (rank === -1 ? PREFERRED.length : rank);
}

/** Local voices, refreshed on `voiceschanged` (Chromium loads them async). */
export function useSpeechVoices(): SpeechSynthesisVoice[] {
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>(() =>
    isSpeechSupported() ? localVoices(window.speechSynthesis.getVoices()) : [],
  );
  useEffect(() => {
    if (!isSpeechSupported()) return;
    const synth = window.speechSynthesis;
    const update = () => setVoices(localVoices(synth.getVoices()));
    update();
    synth.addEventListener('voiceschanged', update);
    return () => synth.removeEventListener('voiceschanged', update);
  }, []);
  return voices;
}

function baseLang(v: SpeechSynthesisVoice): string {
  return v.lang.toLowerCase().replace('_', '-').split('-')[0] ?? '';
}

/** Explicit, installed choice → that voice. Otherwise (auto, or the chosen
 * voice was uninstalled): the best-sounding English voice. Notes are always
 * read in English (the user doesn't want Afrikaans reading), so `_lang` is
 * ignored. Chromium's `default` flag is NOT trusted: on macOS it marks the
 * novelty voice Albert. Null → the engine's default. */
export function pickVoice(
  voices: readonly SpeechSynthesisVoice[],
  preferredUri: string,
  _lang: NoteLanguage | null,
): SpeechSynthesisVoice | null {
  if (preferredUri) {
    const chosen = voices.find((v) => v.voiceURI === preferredUri);
    if (chosen) return chosen;
  }
  const usable = voices.filter((v) => !isNovelty(v));
  const english = usable.filter((v) => baseLang(v) === 'en');
  const pool = english.length > 0 ? english : usable;
  if (pool.length === 0) return null;
  return [...pool].sort((a, b) => quality(a) - quality(b))[0]!;
}

export function makeUtterance(text: string): SpeechSynthesisUtterance {
  return new window.SpeechSynthesisUtterance(text);
}

export function previewVoice(voice: SpeechSynthesisVoice | null, rate: number): void {
  if (!isSpeechSupported()) return;
  const u = makeUtterance('this is how poltergeist reads your notes.');
  if (voice) {
    u.voice = voice;
    u.lang = voice.lang;
  }
  u.rate = rate;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(u);
}
