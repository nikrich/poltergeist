import { Lucide } from './Lucide';

interface Props {
  icon?: string;
  message: string;
  cta?: { label: string; onClick: () => void };
}

export function PanelEmpty({ icon = 'inbox', message, cta }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
      <Lucide name={icon} size={20} color="var(--ink-3)" />
      <p className="m-0 text-12 text-ink-2">{message}</p>
      {cta && (
        <button
          type="button"
          onClick={cta.onClick}
          className="cursor-pointer rounded-r6 border border-hairline-2 bg-transparent px-3 py-1 text-12 text-ink-1 transition-colors hover:bg-vellum"
        >
          {cta.label}
        </button>
      )}
    </div>
  );
}
