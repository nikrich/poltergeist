import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EditorSettings, SettingsScreen } from '../screens/settings';
import { useSettings } from '../stores/settings';
import {
  fakeVoice,
  installFakeSpeech,
  uninstallFakeSpeech,
  type FakeSynth,
} from './helpers/fake-speech';

let synth: FakeSynth;

beforeEach(() => {
  synth = installFakeSpeech();
  synth.voices = [
    fakeVoice('Samantha', 'en-US', { default: true }),
    fakeVoice('Daniel', 'en-GB'),
    fakeVoice('Cloud', 'en-US', { localService: false }),
  ];
  useSettings.setState({ readAloudVoice: '', readAloudRate: 1 });
});

afterEach(() => {
  uninstallFakeSpeech();
  vi.restoreAllMocks();
});

const voiceSelect = () =>
  screen.getByRole('combobox', { name: 'read-aloud voice' }) as HTMLSelectElement;

describe('EditorSettings', () => {
  it('lists auto plus the offline voices only', () => {
    render(<EditorSettings />);
    expect(Array.from(voiceSelect().options).map((o) => o.textContent)).toEqual([
      'auto (match note language)',
      'Daniel — en-GB',
      'Samantha — en-US',
    ]);
  });

  it('choosing a voice saves it', async () => {
    const set = vi.spyOn(window.gb.settings, 'set');
    render(<EditorSettings />);
    fireEvent.change(voiceSelect(), { target: { value: 'Daniel-uri' } });
    await waitFor(() => expect(useSettings.getState().readAloudVoice).toBe('Daniel-uri'));
    expect(set).toHaveBeenCalledWith('readAloudVoice', 'Daniel-uri');
  });

  it('the speed slider saves a value rounded to one decimal', async () => {
    render(<EditorSettings />);
    fireEvent.change(screen.getByRole('slider', { name: 'read-aloud speed' }), {
      target: { value: '1.4000000000000001' },
    });
    await waitFor(() => expect(useSettings.getState().readAloudRate).toBe(1.4));
    expect(screen.getByText('1.4×')).toBeInTheDocument();
  });

  it('says when the chosen voice is no longer installed', () => {
    useSettings.setState({ readAloudVoice: 'Gone-uri' });
    render(<EditorSettings />);
    expect(screen.getByText(/no longer installed/)).toBeInTheDocument();
    expect(voiceSelect().value).toBe('');
  });

  it('play sample speaks with the chosen voice and speed', () => {
    useSettings.setState({ readAloudVoice: 'Daniel-uri', readAloudRate: 1.2 });
    render(<EditorSettings />);
    fireEvent.click(screen.getByRole('button', { name: /play sample/ }));
    expect(synth.last?.voice?.name).toBe('Daniel');
    expect(synth.last?.rate).toBe(1.2);
  });

  it('shows read-aloud as unavailable without speech synthesis', () => {
    uninstallFakeSpeech();
    render(<EditorSettings />);
    expect(screen.queryByRole('combobox', { name: 'read-aloud voice' })).toBeNull();
    expect(screen.getByText('unavailable')).toBeInTheDocument();
  });

  it('shows both editor shortcuts', () => {
    render(<EditorSettings />);
    expect(screen.getByText('⌘ .')).toBeInTheDocument();
    expect(screen.getByText('⌘ ⇧ L')).toBeInTheDocument();
  });

  it('is reachable from the settings nav', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SettingsScreen />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'editor' }));
    expect(screen.getByRole('heading', { name: 'editor' })).toBeInTheDocument();
  });
});
