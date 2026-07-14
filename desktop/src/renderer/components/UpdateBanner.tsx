import { useEffect, useState } from 'react';
import { Btn } from './Btn';
import { Lucide } from './Lucide';

const RELEASES_URL = 'https://github.com/nikrich/poltergeist/releases';

type BannerState =
  | { phase: 'hidden' }
  | { phase: 'available'; version: string; canSelfUpdate: boolean }
  | { phase: 'downloading'; version: string; percent: number }
  | { phase: 'downloaded'; version: string };

export function UpdateBanner() {
  const [state, setState] = useState<BannerState>({ phase: 'hidden' });
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const offAvailable = window.gb.updates.onAvailable(({ version, canSelfUpdate }) => {
      setDismissed(false);
      setState({ phase: 'available', version, canSelfUpdate });
    });
    const offProgress = window.gb.updates.onProgress(({ percent }) => {
      setState((s) =>
        s.phase === 'downloading' || s.phase === 'available'
          ? { phase: 'downloading', version: s.version, percent }
          : s,
      );
    });
    const offDownloaded = window.gb.updates.onDownloaded(({ version }) => {
      setState({ phase: 'downloaded', version });
    });
    return () => {
      offAvailable();
      offProgress();
      offDownloaded();
    };
  }, []);

  if (state.phase === 'hidden' || dismissed) return null;

  async function handleUpdateClick() {
    if (state.phase !== 'available') return;
    if (!state.canSelfUpdate) {
      void window.gb.shell.openExternal(RELEASES_URL);
      return;
    }
    setState({ phase: 'downloading', version: state.version, percent: 0 });
    const result = await window.gb.updates.download();
    if (!result.ok) {
      setState({ phase: 'available', version: state.version, canSelfUpdate: state.canSelfUpdate });
    }
  }

  return (
    <div className="flex h-[38px] flex-shrink-0 items-center gap-3 border-b border-hairline bg-vellum px-[14px] font-body text-13 text-ink-0">
      {state.phase === 'available' && (
        <>
          <span>Poltergeist v{state.version} is available</span>
          <Btn variant="secondary" size="sm" onClick={() => void handleUpdateClick()}>
            Update
          </Btn>
        </>
      )}
      {state.phase === 'downloading' && (
        <>
          <span>Downloading Poltergeist v{state.version}… {state.percent}%</span>
          <Btn variant="secondary" size="sm" disabled>
            Update
          </Btn>
        </>
      )}
      {state.phase === 'downloaded' && (
        <>
          <span>Poltergeist v{state.version} is ready to install</span>
          <Btn variant="primary" size="sm" onClick={() => void window.gb.updates.install()}>
            Restart to update
          </Btn>
        </>
      )}
      <div className="flex-1" />
      <Btn
        variant="ghost"
        size="sm"
        icon={<Lucide name="x" size={14} />}
        onClick={() => setDismissed(true)}
        ariaLabel="dismiss"
      />
    </div>
  );
}
