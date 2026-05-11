import { Lucide } from './Lucide';

interface Props {
  message: string;
  onRetry?: () => void;
}

export function PanelError({ message, onRetry }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
      <Lucide name="alert-triangle" size={20} color="var(--oxblood)" />
      <p className="m-0 max-w-[280px] text-12 text-ink-2">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="cursor-pointer rounded-r6 border border-oxblood/30 bg-oxblood/10 px-3 py-1 text-12 text-oxblood transition-colors hover:bg-oxblood/20"
        >
          retry
        </button>
      )}
    </div>
  );
}
