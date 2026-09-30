import { insertNewline } from '@codemirror/commands';
import { Prec } from '@codemirror/state';
import { keymap } from '@codemirror/view';
import { toggleEmphasis } from './format.js';
import { cycleType, enter, setType } from './commands.js';

const BY_NUMBER = ['scene_heading', 'action', 'character', 'parenthetical', 'dialogue', 'transition', 'centered'];

export function scriptKeymap({ onSave, onToggleFocus, onAi } = {}) {
  return Prec.high(keymap.of([
    { key: 'Tab', run: cycleType(1), preventDefault: true },
    { key: 'Shift-Tab', run: cycleType(-1), preventDefault: true },
    { key: 'Enter', run: enter },
    { key: 'Shift-Enter', run: insertNewline },
    { key: 'Mod-s', run: () => { onSave?.(); return true; }, preventDefault: true },
    { key: 'Mod-Shift-f', run: () => { onToggleFocus?.(); return true; }, preventDefault: true },
    { key: 'Mod-b', run: toggleEmphasis('bold'), preventDefault: true },
    { key: 'Mod-i', run: toggleEmphasis('italic'), preventDefault: true },
    { key: 'Mod-u', run: toggleEmphasis('underline'), preventDefault: true },
    { key: 'Mod-k', run: () => { onAi?.(); return true; }, preventDefault: true },
    ...BY_NUMBER.map((t, i) => ({ key: `Mod-${i + 1}`, run: setType(t), preventDefault: true })),
  ]));
}
