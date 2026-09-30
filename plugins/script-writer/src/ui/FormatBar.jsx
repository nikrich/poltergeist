import { Plus } from 'lucide-react';

export const ELEMENT_OPTIONS = [
  ['scene_heading', 'Scene heading'], ['action', 'Action'], ['character', 'Character'],
  ['parenthetical', 'Parenthetical'], ['dialogue', 'Dialogue'], ['transition', 'Transition'], ['centered', 'Centered'],
];

// onMouseDown preventDefault keeps editor focus/selection; the action runs on click so the keyboard works too.
const noFocusSteal = (e) => e.preventDefault();

export function FormatBar({ currentType, onSetType, onEmphasis, onNewScene }) {
  const known = ELEMENT_OPTIONS.some(([v]) => v === currentType);
  return (
    <div className="sw-formatbar" role="toolbar" aria-label="Formatting">
      <select className="sw-btn" value={known ? currentType : ''} title={'Element (Tab or \u23181\u20137)'}
        onChange={(e) => onSetType(e.target.value)}>
        {!known && <option value="" disabled>{currentType ? currentType.replace('_', ' ') : 'Element'}</option>}
        {ELEMENT_OPTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
      </select>
      <button type="button" className="sw-btn sw-fmt" title={'Bold (\u2318B)'} onMouseDown={noFocusSteal} onClick={() => onEmphasis('bold')}><b>B</b></button>
      <button type="button" className="sw-btn sw-fmt" title={'Italic (\u2318I)'} onMouseDown={noFocusSteal} onClick={() => onEmphasis('italic')}><i>I</i></button>
      <button type="button" className="sw-btn sw-fmt" title={'Underline (\u2318U)'} onMouseDown={noFocusSteal} onClick={() => onEmphasis('underline')}><u>U</u></button>
      <span className="sw-sep" />
      <button type="button" className="sw-btn" title="New scene after this one" onMouseDown={noFocusSteal} onClick={onNewScene}><Plus size={14} />Scene</button>
    </div>
  );
}
