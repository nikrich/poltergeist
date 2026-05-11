import { useSidecar } from '../stores/sidecar';
import { Ghost } from './Ghost';
import { Btn } from './Btn';

export function SidecarSetup() {
  const failure = useSidecar((s) => s.failure);
  const retry = useSidecar((s) => s.retry);
  return (
    <div className="flex h-full w-full items-center justify-center bg-paper p-8">
      <div className="max-w-[520px] flex flex-col items-center gap-4 text-center">
        <Ghost size={48} />
        <h2 className="m-0 font-display text-26 font-semibold tracking-tight-x text-ink-0">
          ghostbrain isn&apos;t running.
        </h2>
        <p className="m-0 text-13 text-ink-2">
          the python backend failed to start. check that python is installed
          (3.11+), and that you&apos;ve run <code className="font-mono text-12 text-ink-1">pip install -e &quot;.[api]&quot;</code> from the project directory.
        </p>
        {failure && (
          <pre className="m-0 max-w-full overflow-auto rounded-md bg-vellum p-3 font-mono text-11 text-ink-2">
            {failure}
          </pre>
        )}
        <Btn variant="primary" size="md" onClick={() => void retry()}>
          retry
        </Btn>
      </div>
    </div>
  );
}
