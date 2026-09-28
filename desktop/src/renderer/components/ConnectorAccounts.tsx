import { useQueryClient } from '@tanstack/react-query';

import { Btn } from './Btn';
import { GmailBackfill } from './GmailBackfill';
import { Lucide } from './Lucide';
import { Pill } from './Pill';
import { Toggle } from './Toggle';
import type { AccountHealth, ConnectorAccount, ConnectorDetail } from '../../shared/api-types';
import { useContexts, useDisconnectConnector, useUpdateAccount } from '../lib/api/hooks';
import { toast } from '../stores/toast';

interface Props {
  connector: ConnectorDetail;
  onAddAccount: () => void;
  onReauth: (accountId: string) => void;
}

function HealthPill({ health }: { health: AccountHealth | null }) {
  if (health === null) return <Pill tone="fog">not synced yet</Pill>;
  if (health.status === 'ok') return <Pill tone="neon">syncing</Pill>;
  if (health.status === 'auth_required') return <Pill tone="oxblood">needs re-auth</Pill>;
  return (
    <Pill tone="oxblood" title={health.error ?? undefined}>
      error
    </Pill>
  );
}

export function ConnectorAccounts({ connector, onAddAccount, onReauth }: Props) {
  const contexts = useContexts();
  const update = useUpdateAccount();
  const disconnect = useDisconnectConnector();
  const qc = useQueryClient();

  if (!Array.isArray(connector.accounts)) return null;
  const accounts = connector.accounts;
  const active = contexts.data?.contexts ?? [];

  const onUpdateError = (e: unknown) =>
    toast.error(e instanceof Error ? e.message : `${connector.displayName}: update failed`);

  const handleRemove = (accountId: string) => {
    if (!window.confirm(`Remove ${accountId}? This deletes its stored credentials.`)) return;
    disconnect.mutate(
      { id: connector.id, account: accountId },
      {
        onSuccess: () => {
          toast.info(`${accountId} removed`);
          qc.invalidateQueries({ queryKey: ['connector', connector.id] });
        },
        onError: (e) =>
          toast.error(e instanceof Error ? e.message : `${accountId}: remove failed`),
      },
    );
  };

  const addButton = (
    <Btn
      variant="secondary"
      size="sm"
      icon={<Lucide name="plus" size={13} />}
      className="self-start"
      onClick={onAddAccount}
    >
      add account
    </Btn>
  );

  if (accounts.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        <div className="text-12 text-ink-2">no accounts yet</div>
        {addButton}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {accounts.map((a: ConnectorAccount) => {
        const archivedContext =
          a.context !== null && !active.includes(a.context) ? a.context : null;
        return (
          <div
            key={a.id}
            data-testid={`account-row-${a.id}`}
            className="flex flex-col gap-2 rounded-r6 border border-hairline bg-paper px-3 py-[10px]"
          >
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate font-mono text-11 text-ink-0">{a.id}</span>
              <HealthPill health={a.health} />
              <button
                type="button"
                aria-label={`remove ${a.id}`}
                onClick={() => handleRemove(a.id)}
                disabled={disconnect.isPending}
                className="text-ink-3 hover:text-oxblood"
              >
                <Lucide name="trash-2" size={12} />
              </button>
            </div>
            <div className="flex items-center gap-3">
              <select
                aria-label={`context for ${a.id}`}
                value={a.context ?? ''}
                onChange={(e) =>
                  update.mutate(
                    { connectorId: connector.id, accountId: a.id, context: e.target.value || null },
                    { onError: onUpdateError },
                  )
                }
                className="rounded-r6 border border-hairline-2 bg-vellum px-2 py-1 font-mono text-11 text-ink-0"
              >
                <option value="">unassigned</option>
                {active.map((ctx) => (
                  <option key={ctx} value={ctx}>
                    {ctx}
                  </option>
                ))}
                {archivedContext !== null && (
                  <option value={archivedContext}>{`${archivedContext} (archived)`}</option>
                )}
              </select>
              <Toggle
                label="enabled"
                ariaLabel={`enabled for ${a.id}`}
                on={a.enabled}
                onChange={(enabled) =>
                  update.mutate(
                    { connectorId: connector.id, accountId: a.id, enabled },
                    { onError: onUpdateError },
                  )
                }
              />
              {a.health?.status === 'auth_required' && (
                <Btn
                  variant="ghost"
                  size="sm"
                  icon={<Lucide name="refresh-cw" size={12} />}
                  onClick={() => onReauth(a.id)}
                >
                  reauthorize
                </Btn>
              )}
            </div>
            {connector.id === 'gmail' && <GmailBackfill accountId={a.id} onReauth={onReauth} />}
          </div>
        );
      })}
      {addButton}
    </div>
  );
}
