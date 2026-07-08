import { useEffect, useRef, useState } from 'react';
import { Btn } from './Btn';
import { Lucide } from './Lucide';
import {
  useAuthStatus,
  useCancelAuth,
  useStartAuth,
  useSubmitAuth,
} from '../lib/api/hooks';
import type { AuthField, AuthSessionView } from '../../shared/api-types';

interface Props {
  connectorId: string;
  onDone: (account?: string) => void;
  onCancel: () => void;
}

/** Renders whatever step the backend's auth-session state machine returns
 * next — one component drives all six auth patterns (paste-token,
 * device-code, browser OAuth, CLI-login grant, etc.) because the branching
 * lives server-side in `next.kind`, not here. */
export function ConnectorAuthFlow({ connectorId, onDone, onCancel }: Props) {
  const [session, setSession] = useState<AuthSessionView | null>(null);
  const startAuth = useStartAuth();
  const submitAuth = useSubmitAuth();
  const cancelAuth = useCancelAuth();

  // Guard against double-firing onDone — status poll and a submit response
  // can both observe "success" in quick succession.
  const doneFired = useRef(false);
  // Track which auth_url we've already opened so a re-render (e.g. after a
  // status poll returns the same open_browser step) doesn't reopen the tab.
  const openedUrlRef = useRef<string | null>(null);

  const start = () => {
    doneFired.current = false;
    openedUrlRef.current = null;
    setSession(null);
    startAuth.mutate(
      { id: connectorId },
      { onSuccess: (data) => setSession(data) },
    );
  };

  // Kick off the session once on mount.
  useEffect(() => {
    start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectorId]);

  const pollEnabled =
    session?.status === 'pending' || session?.status === 'waiting_input';
  const status = useAuthStatus(connectorId, session?.session_id ?? null, pollEnabled);

  useEffect(() => {
    if (status.data) setSession(status.data);
  }, [status.data]);

  useEffect(() => {
    if (session?.status === 'success' && !doneFired.current) {
      doneFired.current = true;
      onDone(session.account ?? undefined);
    }
  }, [session, onDone]);

  useEffect(() => {
    if (!session || session.status !== 'waiting_input' && session.status !== 'pending') return;
    if (session.next.kind === 'open_browser') {
      const url = session.next.auth_url;
      if (url && url !== 'about:blank' && openedUrlRef.current !== url) {
        openedUrlRef.current = url;
        void window.gb.shell.openExternal(url);
      }
    }
  }, [session]);

  const handleCancel = () => {
    if (session?.session_id) {
      cancelAuth.mutate({ id: connectorId, sessionId: session.session_id });
    }
    onCancel();
  };

  if (startAuth.isPending && !session) {
    return (
      <div className="flex flex-col items-center gap-3 p-8 text-center">
        <Lucide name="loader-circle" size={20} color="var(--ink-2)" className="animate-spin" />
        <p className="m-0 text-12 text-ink-2">starting…</p>
      </div>
    );
  }

  if (startAuth.isError && !session) {
    return (
      <ErrorPanel
        message={startAuth.error instanceof Error ? startAuth.error.message : 'failed to start'}
        onRetry={start}
        onCancel={handleCancel}
      />
    );
  }

  if (!session) return null;

  if (session.status === 'error') {
    return (
      <ErrorPanel message={session.error ?? 'authentication failed'} onRetry={start} onCancel={handleCancel} />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <StepBody
        session={session}
        onSubmit={(data) => {
          submitAuth.mutate(
            { id: connectorId, sessionId: session.session_id, data },
            { onSuccess: (result) => setSession(result) },
          );
        }}
        submitting={submitAuth.isPending}
        onRecheck={() => status.refetch()}
      />
      <div className="flex justify-end gap-2">
        <Btn variant="ghost" size="sm" onClick={handleCancel}>
          cancel
        </Btn>
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

interface ErrorPanelProps {
  message: string;
  onRetry: () => void;
  onCancel: () => void;
}

function ErrorPanel({ message, onRetry, onCancel }: ErrorPanelProps) {
  return (
    <div className="flex flex-col items-center gap-3 p-8 text-center">
      <Lucide name="alert-triangle" size={20} color="var(--oxblood)" />
      <p className="m-0 max-w-[280px] text-12 text-oxblood">{message}</p>
      <div className="flex gap-2">
        <Btn variant="secondary" size="sm" onClick={onCancel}>
          cancel
        </Btn>
        <Btn variant="primary" size="sm" onClick={onRetry}>
          retry
        </Btn>
      </div>
    </div>
  );
}

interface StepBodyProps {
  session: AuthSessionView;
  onSubmit: (data: Record<string, unknown>) => void;
  submitting: boolean;
  onRecheck: () => void;
}

function StepBody({ session, onSubmit, submitting, onRecheck }: StepBodyProps) {
  const { next } = session;
  switch (next.kind) {
    case 'need_input':
      return <NeedInputForm fields={next.fields ?? []} message={next.message} onSubmit={onSubmit} submitting={submitting} />;
    case 'show_device_code':
      return (
        <DeviceCodeStep
          userCode={next.user_code}
          verificationUri={next.verification_uri}
          message={next.message}
        />
      );
    case 'open_browser':
      return <SpinnerStep message={next.message ?? 'opening your browser…'} />;
    case 'need_grant':
      return <NeedGrantStep message={next.message} onRecheck={onRecheck} />;
    case 'done':
      return <SpinnerStep message="finishing up…" />;
    default:
      return null;
  }
}

function NeedInputForm({
  fields,
  message,
  onSubmit,
  submitting,
}: {
  fields: AuthField[];
  message: string | null;
  onSubmit: (data: Record<string, unknown>) => void;
  submitting: boolean;
}) {
  const [values, setValues] = useState<Record<string, string>>({});

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(values);
      }}
    >
      {message && <p className="m-0 text-12 text-ink-2">{message}</p>}
      {fields.map((field) => (
        <div key={field.name} className="flex flex-col gap-1">
          <label htmlFor={`auth-field-${field.name}`} className="text-12 font-medium text-ink-0">
            {field.label}
          </label>
          {field.type === 'textarea' ? (
            <textarea
              id={`auth-field-${field.name}`}
              placeholder={field.placeholder}
              value={values[field.name] ?? ''}
              onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
              rows={3}
              className="rounded-sm border border-hairline-2 bg-paper px-2 py-[6px] text-12 text-ink-0 placeholder:text-ink-3 focus:outline-none"
            />
          ) : (
            <input
              id={`auth-field-${field.name}`}
              type={field.type === 'password' ? 'password' : 'text'}
              placeholder={field.placeholder}
              value={values[field.name] ?? ''}
              onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
              className="rounded-sm border border-hairline-2 bg-paper px-2 py-[6px] text-12 text-ink-0 placeholder:text-ink-3 focus:outline-none"
            />
          )}
        </div>
      ))}
      <div className="flex justify-end">
        <Btn type="submit" variant="primary" size="sm" disabled={submitting}>
          {submitting ? 'connecting…' : 'connect'}
        </Btn>
      </div>
    </form>
  );
}

function DeviceCodeStep({
  userCode,
  verificationUri,
  message,
}: {
  userCode: string | null;
  verificationUri: string | null;
  message: string | null;
}) {
  const [copied, setCopied] = useState(false);
  const copyAndOpen = async () => {
    if (userCode) {
      try {
        await navigator.clipboard.writeText(userCode);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      } catch {
        // clipboard failure isn't fatal — the code is still shown on screen
      }
    }
    if (verificationUri) {
      void window.gb.shell.openExternal(verificationUri);
    }
  };
  return (
    <div className="flex flex-col items-center gap-3 p-4 text-center">
      {message && <p className="m-0 text-12 text-ink-2">{message}</p>}
      {userCode && (
        <div className="rounded-r6 border border-hairline-2 bg-vellum px-4 py-2 font-mono text-22 tracking-widest text-ink-0">
          {userCode}
        </div>
      )}
      <Btn
        variant="primary"
        size="sm"
        icon={<Lucide name="copy" size={13} color="#0E0F12" />}
        onClick={copyAndOpen}
      >
        {copied ? 'copied — opening…' : 'copy code & open'}
      </Btn>
      <div className="flex items-center gap-2 text-11 text-ink-2">
        <Lucide name="loader-circle" size={12} color="var(--ink-2)" className="animate-spin" />
        waiting for confirmation…
      </div>
    </div>
  );
}

function SpinnerStep({ message }: { message: string | null }) {
  return (
    <div className="flex flex-col items-center gap-3 p-8 text-center">
      <Lucide name="loader-circle" size={20} color="var(--ink-2)" className="animate-spin" />
      <p className="m-0 text-12 text-ink-2">{message}</p>
    </div>
  );
}

function NeedGrantStep({ message, onRecheck }: { message: string | null; onRecheck: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 p-6 text-center">
      {message && <p className="m-0 max-w-[320px] text-12 text-ink-2">{message}</p>}
      <Btn variant="secondary" size="sm" icon={<Lucide name="refresh-cw" size={13} />} onClick={onRecheck}>
        re-check
      </Btn>
    </div>
  );
}
