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

/** Offline voices only: the user approved OS voices, never a network TTS. */
export function localVoices(all: readonly SpeechSynthesisVoice[]): SpeechSynthesisVoice[] {
  return all
    .filter((v) => v.localService)
    .sort((a, b) => a.lang.localeCompare(b.lang) || a.name.localeCompare(b.name));
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
 * voice was uninstalled): a voice for the note's language, preferring the OS
 * default among them; else the OS default voice; else null (engine default). */
export function pickVoice(
  voices: readonly SpeechSynthesisVoice[],
  preferredUri: string,
  lang: NoteLanguage | null,
): SpeechSynthesisVoice | null {
  if (preferredUri) {
    const chosen = voices.find((v) => v.voiceURI === preferredUri);
    if (chosen) return chosen;
  }
  if (lang) {
    const matches = voices.filter((v) => baseLang(v) === lang);
    if (matches.length > 0) return matches.find((v) => v.default) ?? matches[0]!;
  }
  return voices.find((v) => v.default) ?? null;
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
