import { useCallback, useEffect, useState } from 'react';

export const DEFAULT_UI = { sceneNav: true, panel: 'page', dark: false, paper: 'letter', focus: false, sceneNumbersDefault: false };

export function useUiSettings(plugin) {
  const [ui, setUi] = useState(DEFAULT_UI);
  useEffect(() => {
    let live = true;
    plugin.settings.get('ui').then((v) => { if (live && v && typeof v === 'object') setUi({ ...DEFAULT_UI, ...v }); }).catch(() => {});
    return () => { live = false; };
  }, [plugin]);
  const patch = useCallback((p) => {
    setUi((cur) => {
      const next = { ...cur, ...p };
      plugin.settings.set('ui', next).catch(() => {});
      return next;
    });
  }, [plugin]);
  return [ui, patch];
}
