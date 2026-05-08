import { Lucide } from './Lucide';

interface Props {
  icon: string;
  text: string;
  // style?: transitional — call sites migrate in B.2.b–f and this prop is dropped in B.2.f
  style?: React.CSSProperties;
}

export function Catch({ icon, text }: Props) {
  return (
    <div className="flex items-start gap-2 rounded-sm px-[6px] py-2 text-12 leading-[1.4] text-ink-0">
      <Lucide name={icon} size={12} color="var(--neon)" className="mt-[3px]" />
      <span>{text}</span>
    </div>
  );
}
