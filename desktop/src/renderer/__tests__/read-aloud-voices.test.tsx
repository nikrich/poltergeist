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

describe('voices', () => {
  it('isSpeechSupported reflects the API being present', () => {
    expect(isSpeechSupported()).toBe(false);
    installFakeSpeech();
    expect(isSpeechSupported()).toBe(true);
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
    expect(pickVoice([SAMANTHA, DANIEL, AF], 'Gone-uri', 'af')).toBe(AF);
    expect(pickVoice([SAMANTHA, DANIEL], 'Gone-uri', null)).toBe(SAMANTHA);
  });

  it('pickVoice: auto matches the note language, preferring the default voice', () => {
    expect(pickVoice([DANIEL, SAMANTHA, AF], '', 'af')).toBe(AF);
    expect(pickVoice([DANIEL, SAMANTHA], '', 'en')).toBe(SAMANTHA);
    expect(pickVoice([DANIEL], '', 'en')).toBe(DANIEL);
  });

  it('pickVoice: no voice for the language falls back to the OS default, then null', () => {
    expect(pickVoice([SAMANTHA, DANIEL], '', 'af')).toBe(SAMANTHA);
    expect(pickVoice([DANIEL], '', 'af')).toBeNull();
    expect(pickVoice([], '', null)).toBeNull();
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
