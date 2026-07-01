import {
  useDisconnectMicrosoft,
  useMicrosoftAuthStatus,
  useStartMicrosoftAuth,
} from '../lib/api/hooks';

export default function MicrosoftConnectCard() {
  const status = useMicrosoftAuthStatus();
  const start = useStartMicrosoftAuth();
  const disconnect = useDisconnectMicrosoft();

  const state = status.data?.state ?? 'idle';
  const account = status.data?.account ?? null;
  const error = status.data?.error ?? null;
  const pending = state === 'pending';

  return (
    <div className="mb-4 rounded-r6 border border-ink-4/40 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-12 font-medium text-ink-1">Microsoft 365</div>
          <div className="mt-[2px] text-11 text-ink-2">
            {state === 'connected' && account
              ? `Connected as ${account}`
              : pending
                ? 'Waiting for sign-in in your browser…'
                : 'Not connected'}
          </div>
        </div>
        {state === 'connected' ? (
          <button
            type="button"
            className="text-11 text-ink-2 underline"
            onClick={() => void disconnect.mutateAsync()}
          >
            Disconnect
          </button>
        ) : (
          <button
            type="button"
            className="rounded-r6 bg-ink-1 px-3 py-1 text-11 text-paper disabled:opacity-50"
            disabled={pending}
            onClick={() => void start.mutateAsync()}
          >
            {pending ? 'Signing in…' : state === 'error' ? 'Retry' : 'Connect Microsoft'}
          </button>
        )}
      </div>
      {error ? (
        <div className="mt-2 text-11 text-oxblood">{error}</div>
      ) : null}
    </div>
  );
}
