import { useEffect, useState } from 'react';

import { useLlmProviders, useLlmSettings, useUpdateLlmSettings } from '../lib/api/hooks';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { fromSidecarProvider, toSidecarProvider } from '../../shared/llm-provider';
import type { LlmProvider } from '../../shared/types';

const RENDERER_PROVIDERS: LlmProvider[] = ['claude', 'codex', 'gemini', 'local'];

const selectClass =
  'cursor-pointer rounded-sm border border-hairline-2 bg-vellum px-[10px] py-[6px] font-mono text-11 text-ink-0 disabled:cursor-not-allowed disabled:opacity-60';

interface Props {
  /** When true, every provider is selectable regardless of its diagnostics
   * probe (failed ones keep the "<id> — <reason>" label, just not disabled)
   * and a change always sends the PUT. Used by the settings panel, which is
   * where a provider gets configured — e.g. `local` needs to be selectable
   * to enter a base URL even while its server is down. The chat-header
   * switcher (default, `false`) keeps failed providers disabled. */
  allowUnavailable?: boolean;
}

/** Shared provider dropdown — mounted in the chat header and reused by the
 * AI-provider settings panel. By default, providers whose diagnostics probe
 * is not `ok` render as disabled options carrying the failure reason; jsdom's
 * `fireEvent.change` bypasses a real browser's disabled-option handling, so
 * the change handler re-checks `ok` itself before sending a PUT. Pass
 * `allowUnavailable` to skip both the disabled state and that guard. */
export function ProviderSwitcher({ allowUnavailable = false }: Props) {
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
    if (!allowUnavailable && diagnostics && !diagnostics.ok) return; // guard: disabled option, no PUT
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
        const failed = diagnostics ? !diagnostics.ok : false;
        const label = failed ? `${p} — ${diagnostics?.reason}` : p;
        return (
          <option key={p} value={p} disabled={failed && !allowUnavailable}>
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
