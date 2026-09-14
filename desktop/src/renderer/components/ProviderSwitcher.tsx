import { useEffect, useState } from 'react';

import { useLlmProviders, useLlmSettings, useUpdateLlmSettings } from '../lib/api/hooks';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { fromSidecarProvider, toSidecarProvider } from '../../shared/llm-provider';
import type { LlmProvider } from '../../shared/types';

const RENDERER_PROVIDERS: LlmProvider[] = ['claude', 'codex', 'gemini', 'local'];

const selectClass =
  'cursor-pointer rounded-sm border border-hairline-2 bg-vellum px-[10px] py-[6px] font-mono text-11 text-ink-0 disabled:cursor-not-allowed disabled:opacity-60';

/** Shared provider dropdown — mounted in the chat header and reused by the
 * AI-provider settings panel. Providers whose diagnostics probe is not `ok`
 * render as disabled options carrying the failure reason; jsdom's
 * `fireEvent.change` bypasses a real browser's disabled-option handling, so
 * the change handler re-checks `ok` itself before sending a PUT. */
export function ProviderSwitcher() {
  const providersQuery = useLlmProviders();
  const settingsQuery = useLlmSettings();
  const updateSettings = useUpdateLlmSettings();
  const setSetting = useSettings((s) => s.set);

  const [pending, setPending] = useState<LlmProvider | null>(null);

  const active = settingsQuery.data ? fromSidecarProvider(settingsQuery.data.provider) : null;

  // Clear the optimistic pending value once the settled data reflects it.
  useEffect(() => {
    if (pending !== null && active === pending) setPending(null);
  }, [active, pending]);

  const value = pending ?? active ?? '';
  const providers = providersQuery.data?.providers;

  const handleChange = (next: LlmProvider) => {
    const sidecarId = toSidecarProvider(next);
    const diagnostics = providers?.[sidecarId];
    if (diagnostics && !diagnostics.ok) return; // guard: disabled option, no PUT
    setPending(next);
    void updateSettings
      .mutateAsync({ provider: sidecarId })
      .then(() => trySet(setSetting, next))
      .catch((err) => {
        setPending(null);
        toast.error(err instanceof Error ? err.message : 'failed to switch provider');
      });
  };

  return (
    <select
      aria-label="provider"
      className={selectClass}
      value={value}
      onChange={(e) => handleChange(e.target.value as LlmProvider)}
    >
      {value === '' && <option value="" disabled />}
      {RENDERER_PROVIDERS.map((p) => {
        const diagnostics = providers?.[toSidecarProvider(p)];
        const disabled = diagnostics ? !diagnostics.ok : false;
        const label = disabled ? `${p} — ${diagnostics?.reason}` : p;
        return (
          <option key={p} value={p} disabled={disabled}>
            {label}
          </option>
        );
      })}
    </select>
  );
}

async function trySet(
  setSetting: (
    key: 'llmProvider',
    value: LlmProvider,
  ) => Promise<{ ok: true } | { ok: false; error: string }>,
  provider: LlmProvider,
) {
  const r = await setSetting('llmProvider', provider);
  if (!r.ok) toast.error(r.error);
}
