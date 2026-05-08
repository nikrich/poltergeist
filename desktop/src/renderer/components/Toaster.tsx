import { useToasts } from '../stores/toast';

export function Toaster() {
  const toasts = useToasts((s) => s.toasts);
  return (
    <div className="pointer-events-none fixed bottom-10 right-5 z-[1000] flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="rounded-md border border-hairline-2 bg-vellum px-[14px] py-[10px] font-mono text-12 text-ink-0 shadow-card"
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
