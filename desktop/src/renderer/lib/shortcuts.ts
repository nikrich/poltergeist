import { isMac } from './platform';

export interface Shortcut {
  mod: 'cmd-shift' | 'ctrl-shift';
  key: string;
}

export function format(s: Shortcut): string {
  const prefix = isMac ? '⌘ ⇧' : 'Ctrl ⇧';
  return `${prefix} ${s.key}`;
}

export const HOTKEYS: Array<{ label: string; shortcut: Shortcut }> = [
  { label: 'ask the archive', shortcut: { mod: 'cmd-shift', key: 'K' } },
  { label: 'quick capture', shortcut: { mod: 'cmd-shift', key: 'C' } },
  { label: 'start recording', shortcut: { mod: 'cmd-shift', key: 'R' } },
  { label: 'stop recording', shortcut: { mod: 'cmd-shift', key: 'S' } },
  { label: 'open vault', shortcut: { mod: 'cmd-shift', key: 'V' } },
  { label: 'toggle poltergeist window', shortcut: { mod: 'cmd-shift', key: 'G' } },
];
