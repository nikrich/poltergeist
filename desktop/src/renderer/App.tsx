import { useEffect } from 'react';
import { useSettings } from './stores/settings';
import { useNavigation } from './stores/navigation';
import { WindowChrome } from './components/WindowChrome';
import { Sidebar } from './components/Sidebar';
import { StatusBar } from './components/StatusBar';
import { Toaster } from './components/Toaster';
import { TodayScreen } from './screens/today';
import { ConnectorsScreen } from './screens/connectors';
import { MeetingsScreen } from './screens/meetings';
import { CaptureScreen } from './screens/capture';
import { VaultScreen } from './screens/vault';

function ScreenStub({ name }: { name: string }) {
  return (
    <div
      style={{
        flex: 1,
        display: 'grid',
        placeItems: 'center',
        color: 'var(--ink-2)',
        fontFamily: 'var(--font-mono)',
        fontSize: 14,
      }}
    >
      {name} screen — coming next
    </div>
  );
}

export default function App() {
  const { theme, density, ready, hydrate } = useSettings();
  const active = useNavigation((s) => s.active);

  useEffect(() => {
    hydrate();
  }, [hydrate]);
  useEffect(() => {
    if (!ready) return;
    document.body.dataset.theme = theme;
    document.body.dataset.density = density;
  }, [theme, density, ready]);

  if (!ready) {
    return <div className="bg-paper text-ink-2 grid h-full place-items-center">…</div>;
  }
  return (
    <WindowChrome>
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Sidebar />
        <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {active === 'today' && <TodayScreen />}
          {active === 'connectors' && <ConnectorsScreen />}
          {active === 'meetings' && <MeetingsScreen />}
          {active === 'capture' && <CaptureScreen />}
          {active === 'vault' && <VaultScreen />}
          {active === 'settings' && <ScreenStub name={active} />}
        </main>
      </div>
      <StatusBar />
      <Toaster />
    </WindowChrome>
  );
}
