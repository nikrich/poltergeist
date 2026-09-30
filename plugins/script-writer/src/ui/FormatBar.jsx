import { Plus } from 'lucide-react';

export const ELEMENT_OPTIONS = [
  ['scene_heading', 'Scene heading'], ['action', 'Action'], ['character', 'Character'],
  ['parenthetical', 'Parenthetical'], ['dialogue', 'Dialogue'], ['transition', 'Transition'], ['centered', 'Centered'],
];

// onMouseDown + preventDefault keeps the editor focus and selection intact.
const keep = (fn) => (e) => { e.preventDefault(); fn(); };

export function FormatBar({ currentType, onSetType, onEmphasis, onNewScene }) {
  const known = ELEMENT_OPTIONS.some(([v]) => v === currentType);
  return (
    <div className="sw-formatbar" role="toolbar" aria-label="Formatting">
      <select className="sw-btn" value={known ? currentType : ''} title={'Element (Tab or \u23181\u20137)'}
        onChange={(e) => onSetType(e.target.value)}>
        {!known && <option value="" disabled>{currentType ? currentType.replace('_', ' ') : 'Element'}</option>}
        {ELEMENT_OPTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
      </select>
      <button type="button" className="sw-btn sw-fmt" title={'Bold (\u2318B)'} onMouseDown={keep(() => onEmphasis('bold'))}><b>B</b></button>
      <button type="button" className="sw-btn sw-fmt" title={'Italic (\u2318I)'} onMouseDown={keep(() => onEmphasis('italic'))}><i>I</i></button>
      <button type="button" className="sw-btn sw-fmt" title={'Underline (\u2318U)'} onMouseDown={keep(() => onEmphasis('underline'))}><u>U</u></button>
      <span className="sw-sep" />
      <button type="button" className="sw-btn" title="New scene after this one" onMouseDown={keep(onNewScene)}><Plus size={14} />Scene</button>
    </div>
  );
}
