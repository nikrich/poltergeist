export function EditorScreen({ path, onBack }) {
  return (
    <div className="sw-lib">
      <button type="button" className="sw-btn" onClick={onBack}>Back</button>
      <p className="sw-muted">{path}</p>
    </div>
  );
}
