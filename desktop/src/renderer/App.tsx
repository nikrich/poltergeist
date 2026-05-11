import { useEffect } from 'react';
import { useSettings } from './stores/settings';
import { useNavigation } from './stores/navigation';
import { useSidecar } from './stores/sidecar';
import { WindowChrome } from './components/WindowChrome';
import { Sidebar } from './components/Sidebar';
import { StatusBar } from './components/StatusBar';
import { Toaster } from './components/Toaster';
import { SidecarSetup } from './components/SidecarSetup';
import { TodayScreen } from './screens/today';
import { ConnectorsScreen } from './screens/connectors';
import { MeetingsScreen } from './screens/meetings';
import { CaptureScreen } from './screens/capture';
import { VaultScreen } from './screens/vault';
import { SettingsScreen } from './screens/settings';

export default function App() {
  const { theme, density, ready, hydrate } = useSettings();
  const active = useNavigation((s) => s.active);
  const setActive = useNavigation((s) => s.setActive);
  const sidecarStatus = useSidecar((s) => s.status);
  const setReady = useSidecar((s) => s.setReady);
  const setFailed = useSidecar((s) => s.setFailed);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    if (!ready) return;
    document.body.dataset.theme = theme;
    document.body.dataset.density = density;
  }, [theme, density, ready]);

  useEffect(() => {
    return window.gb.on('nav:settings', () => setActive('settings'));
  }, [setActive]);

  useEffect(() => {
    const offReady = window.gb.on('sidecar:ready', () => setReady());
    const offFailed = window.gb.on('sidecar:failed', (info) => setFailed(info.reason));
    return () => {
      offReady();
      offFailed();
    };
  }, [setReady, setFailed]);

  if (!ready) {
    return <div className="bg-paper text-ink-2 grid h-full place-items-center">…</div>;
  }

  if (sidecarStatus === 'failed') {
    return <SidecarSetup />;
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
          {active === 'settings' && <SettingsScreen />}
        </main>
      </div>
      <StatusBar />
      <Toaster />
    </WindowChrome>
  );
}
