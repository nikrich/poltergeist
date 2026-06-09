import { useEffect } from 'react';
import { toast } from './stores/toast';
import { useSettings } from './stores/settings';
import { useNavigation } from './stores/navigation';
import { useSelectedEvent } from './stores/selected-event';
import { useSidecar } from './stores/sidecar';
import { useSchedulerStatus } from './lib/api/hooks';
import { WindowChrome } from './components/WindowChrome';
import { Sidebar } from './components/Sidebar';
import { StatusBar } from './components/StatusBar';
import { Toaster } from './components/Toaster';
import { NoteView } from './components/NoteView';
import { SidecarSetup } from './components/SidecarSetup';
import { TodayScreen } from './screens/today';
import { ConnectorsScreen } from './screens/connectors';
import { MeetingsScreen } from './screens/meetings';
import { CaptureScreen } from './screens/capture';
import { VaultScreen } from './screens/vault';
import { DailyScreen } from './screens/daily';
import { SetupScreen } from './screens/setup';
import { SettingsScreen } from './screens/settings';
import { JotsScreen } from './screens/jots';

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

  useEffect(() => {
    return window.gb.on('meetings:openPrep', (eventId: unknown) => {
      if (typeof eventId !== 'string') return;
      useNavigation.getState().setActive('meetings');
      useSelectedEvent.getState().setSelectedEventId(eventId);
    });
  }, []);

  // Surface overlay autosave failures as a toast. The overlay broadcasts
  // window.gb.jot.onSaveFailed whenever the sidecar write fails; without this
  // listener the error is silently swallowed.
  useEffect(() => {
    return window.gb.jot.onSaveFailed(({ error }) => {
      toast.error(`jot save failed: ${error}`);
    });
  }, []);

  // Mirror scheduler health into the tray so the user sees the alert dot even
  // when the main window is hidden. The query polls every 15s; when scheduler
  // is off we still clear any stale failing state on mount.
  const schedulerStatus = useSchedulerStatus({ intervalMs: 15_000 });
  useEffect(() => {
    if (sidecarStatus !== 'ready') return;
    const data = schedulerStatus.data;
    if (!data || !data.enabled) {
      void window.gb.tray.setFailing([]);
      return;
    }
    const failing = Object.values(data.jobs)
      .filter((j) => j.last_run_ok === false)
      .map((j) => j.name);
    void window.gb.tray.setFailing(failing);
  }, [schedulerStatus.data, sidecarStatus]);

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
          {active === 'daily' && <DailyScreen />}
          {active === 'setup' && <SetupScreen />}
          {active === 'settings' && <SettingsScreen />}
          {active === 'jots' && <JotsScreen />}
        </main>
      </div>
      <StatusBar />
      <Toaster />
      <NoteView />
    </WindowChrome>
  );
}
