import { useCallback, useRef, useState } from 'react';
import { EditorScreen } from './EditorScreen.jsx';
import { Library } from './Library.jsx';

export function App({ plugin }) {
  const [route, setRoute] = useState({ name: 'library' });
  const [toast, setToast] = useState(null);
  const timer = useRef(null);
  const notify = useCallback((msg, kind = 'info') => {
    clearTimeout(timer.current);
    setToast({ msg, kind });
    timer.current = setTimeout(() => setToast(null), 6000);
  }, []);
  return (
    <div className="sw-root">
      {route.name === 'library'
        ? <Library plugin={plugin} notify={notify} onOpen={(path) => setRoute({ name: 'editor', path })} />
        : <EditorScreen key={route.path} plugin={plugin} path={route.path} notify={notify} onBack={() => setRoute({ name: 'library' })} />}
      {toast && <div className={`sw-toast${toast.kind === 'error' ? ' sw-error' : ''}`} role="status">{toast.msg}</div>}
    </div>
  );
}
