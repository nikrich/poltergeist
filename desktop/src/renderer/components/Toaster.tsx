import { useToasts, type ToastKind } from '../stores/toast';

const KIND_CLASSES: Record<ToastKind, string> = {
  info: 'border-hairline-2 bg-vellum text-ink-0',
  success: 'border-neon/40 bg-neon/12 text-neon-ink',
  error: 'border-oxblood/40 bg-oxblood/15 text-oxblood',
};

export function Toaster() {
  const toasts = useToasts((s) => s.toasts);
  return (
    <div className="pointer-events-none fixed bottom-10 right-5 z-[1000] flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          role={t.kind === 'error' ? 'alert' : 'status'}
          className={`rounded-md border px-[14px] py-[10px] font-mono text-12 shadow-card ${KIND_CLASSES[t.kind]}`}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
