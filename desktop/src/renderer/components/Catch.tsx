import { Lucide } from './Lucide';

interface Props {
  icon: string;
  text: string;
}

export function Catch({ icon, text }: Props) {
  return (
    <div className="flex items-start gap-2 rounded-sm px-[6px] py-2 text-12 leading-[1.4] text-ink-0">
      <Lucide name={icon} size={12} color="var(--neon)" className="mt-[3px]" />
      <span>{text}</span>
    </div>
  );
}
