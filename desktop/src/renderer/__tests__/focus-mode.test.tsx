import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  focusActiveNow,
  useFocusActive,
  useFocusModeShortcuts,
  useFocusSurface,
  useFocusSurfaces,
} from '../lib/focus-mode';
import { FocusBar } from '../components/FocusBar';
import { useSettings } from '../stores/settings';

function Harness({ surface }: { surface: boolean }) {
  useFocusSurface(surface);
  useFocusModeShortcuts();
  const active = useFocusActive();
  return <div data-testid="state">{active ? 'on' : 'off'}</div>;
}

beforeEach(() => {
  useSettings.setState({ focusMode: false });
  useFocusSurfaces.setState({ count: 0 });
});

afterEach(() => {
  useSettings.setState({ focusMode: false });
  useFocusSurfaces.setState({ count: 0 });
});

describe('focus mode core', () => {
  it('is inactive without an editor surface, even when the flag is on', () => {
    useSettings.setState({ focusMode: true });
    render(<Harness surface={false} />);
    expect(screen.getByTestId('state')).toHaveTextContent('off');
    expect(focusActiveNow()).toBe(false);
  });

  it('is active when the flag is on and a surface is mounted', () => {
    useSettings.setState({ focusMode: true });
    render(<Harness surface />);
    expect(screen.getByTestId('state')).toHaveTextContent('on');
    expect(focusActiveNow()).toBe(true);
  });

  it('unmounting the surface deactivates it; release is idempotent', () => {
    const release = useFocusSurfaces.getState().register();
    expect(useFocusSurfaces.getState().count).toBe(1);
    release();
    release();
    expect(useFocusSurfaces.getState().count).toBe(0);
  });

  it('⌘. toggles focus while an editor is on screen', async () => {
    render(<Harness surface />);
    fireEvent.keyDown(window, { key: '.', metaKey: true });
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('on'));
    fireEvent.keyDown(window, { key: '.', metaKey: true });
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('off'));
  });

  it('⌘. does nothing with no editor on screen', async () => {
    render(<Harness surface={false} />);
    fireEvent.keyDown(window, { key: '.', metaKey: true });
    await act(async () => {});
    expect(useSettings.getState().focusMode).toBe(false);
  });

  it('Esc leaves focus mode', async () => {
    useSettings.setState({ focusMode: true });
    render(<Harness surface />);
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(useSettings.getState().focusMode).toBe(false));
  });

  it('Esc already handled by the editor does not leave focus', async () => {
    useSettings.setState({ focusMode: true });
    render(<Harness surface />);
    const menu = document.createElement('div');
    document.body.append(menu);
    // ProseMirror calls preventDefault when a suggestion/slash menu consumes Esc.
    menu.addEventListener('keydown', (e) => e.preventDefault());
    fireEvent.keyDown(menu, { key: 'Escape' });
    await act(async () => {});
    expect(useSettings.getState().focusMode).toBe(true);
    menu.remove();
  });

  it('FocusBar exit button turns focus off', async () => {
    useSettings.setState({ focusMode: true });
    render(<FocusBar />);
    fireEvent.click(screen.getByRole('button', { name: 'exit focus mode' }));
    await waitFor(() => expect(useSettings.getState().focusMode).toBe(false));
  });
});
