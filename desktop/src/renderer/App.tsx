import { useEffect, useState } from 'react';
import type { Settings } from '../preload/types';

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  useEffect(() => {
    window.gb.settings.getAll().then(setSettings);
  }, []);
  return (
    <div className="bg-paper text-ink-0 p-6 h-full font-body">
      <h1 className="font-display text-4xl tracking-tight">ghostbrain</h1>
      <p className="text-ink-2 font-mono text-xs uppercase tracking-widest">tokens online</p>
      <pre className="bg-vellum text-ink-1 mt-4 rounded-md p-3 text-xs">
        {JSON.stringify(settings, null, 2)}
      </pre>
    </div>
  );
}
