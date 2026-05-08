type Tone = 'neon' | 'moss' | 'oxblood' | 'fog' | 'outline';

interface Props {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
  // style?: transitional — call sites migrate in B.2.b–f and this prop is dropped in B.2.f
  style?: React.CSSProperties;
}

const toneClasses: Record<Tone, string> = {
  neon: 'bg-neon/15 text-neon',
  moss: 'bg-moss/20 text-[#A2C795]',
  oxblood: 'bg-oxblood/15 text-[#FF8A7C]',
  fog: 'bg-fog text-ink-1',
  outline: 'bg-transparent text-ink-2 border border-hairline-2',
};

export function Pill({ tone = 'neon', children, className = '' }: Props) {
  return (
    <span
      className={`inline-flex items-center gap-[5px] whitespace-nowrap rounded-sm px-[7px] py-[2px] font-mono text-10 font-medium lowercase ${toneClasses[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
