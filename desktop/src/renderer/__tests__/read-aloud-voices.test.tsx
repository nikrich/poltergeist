import { afterEach, describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import {
  isSpeechSupported,
  localVoices,
  pickVoice,
  previewVoice,
  useSpeechVoices,
} from '../lib/read-aloud/voices';
import { fakeVoice, installFakeSpeech, uninstallFakeSpeech } from './helpers/fake-speech';

afterEach(() => uninstallFakeSpeech());

const SAMANTHA = fakeVoice('Samantha', 'en-US', { default: true });
const DANIEL = fakeVoice('Daniel', 'en-GB');
const AF = fakeVoice('Afrikaans', 'af-ZA');
const NETWORK = fakeVoice('Cloud', 'en-US', { localService: false });
const ALBERT = fakeVoice('Albert', 'en-US', { default: true });
const BAD_NEWS = fakeVoice('Bad News', 'en-US');
const ZARVOX = fakeVoice('Zarvox', 'en-US');
const KAREN = fakeVoice('Karen', 'en-AU');
const TESSA = fakeVoice('Tessa', 'en-ZA');
const SAMANTHA_PLAIN = fakeVoice('Samantha', 'en-US');
const SAMANTHA_PREMIUM = fakeVoice('Samantha (Premium)', 'en-US');
const XANDER = fakeVoice('Xander', 'nl-NL');

describe('voices', () => {
  it('isSpeechSupported reflects the API being present', () => {
    expect(isSpeechSupported()).toBe(false);
    installFakeSpeech();
    expect(isSpeechSupported()).toBe(true);
  });

  it('localVoices drops novelty voices so the settings picker never offers them', () => {
    expect(localVoices([ALBERT, BAD_NEWS, TESSA, ZARVOX]).map((v) => v.name)).toEqual(['Tessa']);
  });

  it('localVoices drops network voices and sorts by language then name', () => {
    expect(localVoices([SAMANTHA, NETWORK, AF, DANIEL]).map((v) => v.name)).toEqual([
      'Afrikaans',
      'Daniel',
      'Samantha',
    ]);
  });

  it('pickVoice: an installed explicit choice wins', () => {
    expect(pickVoice([SAMANTHA, DANIEL, AF], 'Daniel-uri', 'af')).toBe(DANIEL);
  });

  it('pickVoice: a missing explicit choice falls back to auto', () => {
    expect(pickVoice([SAMANTHA, DANIEL, AF], 'Gone-uri', 'af')).toBe(SAMANTHA);
    expect(pickVoice([SAMANTHA, DANIEL], 'Gone-uri', null)).toBe(SAMANTHA);
  });

  it('pickVoice: auto picks the best English voice by quality, not the default flag', () => {
    expect(pickVoice([DANIEL, SAMANTHA], '', 'en')).toBe(SAMANTHA);
    expect(pickVoice([DANIEL], '', 'en')).toBe(DANIEL);
  });

  it('pickVoice: never the novelty voice Chromium flags as default on macOS (Albert)', () => {
    // The real macOS list: Chromium marks Albert, a strained novelty voice, as default.
    const voices = [ALBERT, BAD_NEWS, DANIEL, KAREN, TESSA, SAMANTHA_PLAIN];
    expect(pickVoice(voices, '', 'en')).toBe(TESSA);
    expect(pickVoice(voices, '', null)).toBe(TESSA);
    expect(pickVoice([ALBERT, DANIEL], '', 'en')).toBe(DANIEL);
  });

  it('pickVoice: prefers Premium/Enhanced variants of a voice', () => {
    expect(pickVoice([TESSA, SAMANTHA_PREMIUM], '', 'en')).toBe(SAMANTHA_PREMIUM);
  });

  it('pickVoice: reads every note in English, whatever its language (no Afrikaans reading)', () => {
    expect(pickVoice([ALBERT, TESSA, XANDER, AF], '', 'af')).toBe(TESSA);
    expect(pickVoice([SAMANTHA, DANIEL], '', 'af')).toBe(SAMANTHA);
    expect(pickVoice([], '', null)).toBeNull();
  });

  it('pickVoice: only novelty voices installed → null (engine default)', () => {
    expect(pickVoice([ALBERT, BAD_NEWS], '', 'en')).toBeNull();
  });

  it('useSpeechVoices picks up voices that load late', () => {
    const synth = installFakeSpeech();
    const { result } = renderHook(() => useSpeechVoices());
    expect(result.current).toEqual([]);
    act(() => synth.setVoices([SAMANTHA, NETWORK]));
    expect(result.current.map((v) => v.name)).toEqual(['Samantha']);
  });

  it('useSpeechVoices is empty and harmless without speech support', () => {
    const { result } = renderHook(() => useSpeechVoices());
    expect(result.current).toEqual([]);
  });

  it('previewVoice cancels anything playing and speaks a sample with voice and rate', () => {
    const synth = installFakeSpeech();
    previewVoice(DANIEL, 1.3);
    expect(synth.cancel).toHaveBeenCalled();
    expect(synth.last?.voice).toBe(DANIEL);
    expect(synth.last?.rate).toBe(1.3);
    expect(synth.last?.text).toMatch(/poltergeist/);
  });
});
