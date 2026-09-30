const FIELDS = [
  ['title', 'Title'], ['credit', 'Credit'], ['author', 'Author'],
  ['source', 'Source (optional)'], ['draft_date', 'Draft date'], ['contact', 'Contact'],
];

export function TitlePageFields({ value, onChange }) {
  return FIELDS.map(([key, label]) => (
    <label key={key} className="sw-field">
      <span className="sw-muted">{label}</span>
      {key === 'contact'
        ? <textarea rows={3} value={value[key] ?? ''} onChange={(e) => onChange({ ...value, [key]: e.target.value })} />
        : <input value={value[key] ?? ''} onChange={(e) => onChange({ ...value, [key]: e.target.value })} />}
    </label>
  ));
}
