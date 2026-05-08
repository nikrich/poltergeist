type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'record';
type Size = 'sm' | 'md' | 'lg';

interface Props {
  variant?: Variant;
  size?: Size;
  icon?: React.ReactNode;
  iconRight?: React.ReactNode;
  children?: React.ReactNode;
  onClick?: () => void;
  className?: string;
  disabled?: boolean;
  type?: 'button' | 'submit';
  ariaLabel?: string;
  // style?: transitional — call sites migrate in B.2.b–f and this prop is dropped in B.2.f
  style?: React.CSSProperties;
}

const sizeClasses: Record<Size, string> = {
  sm: 'px-[10px] py-[6px] text-12 gap-[6px]',
  md: 'px-[14px] py-2 text-13 gap-[7px]',
  lg: 'px-[18px] py-[11px] text-14 gap-2',
};

const variantClasses: Record<Variant, string> = {
  primary: 'bg-neon text-[#0E0F12] border border-transparent hover:bg-neon-dark',
  secondary: 'bg-vellum text-ink-0 border border-hairline-2 hover:bg-fog',
  ghost: 'bg-transparent text-ink-1 border border-transparent hover:bg-vellum',
  danger: 'bg-oxblood/10 text-oxblood border border-oxblood/30 hover:bg-oxblood/20',
  record: 'bg-oxblood text-[#0E0F12] border border-transparent hover:bg-[#E8584C]',
};

export function Btn({
  variant = 'primary',
  size = 'md',
  icon,
  iconRight,
  children,
  onClick,
  className = '',
  disabled,
  type = 'button',
  ariaLabel,
}: Props) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      className={`inline-flex items-center justify-center whitespace-nowrap rounded-r6 font-body font-medium transition-all duration-[120ms] ease-[cubic-bezier(.2,.8,.2,1)] disabled:cursor-not-allowed disabled:opacity-50 ${sizeClasses[size]} ${variantClasses[variant]} ${className}`}
    >
      {icon}
      {children}
      {iconRight}
    </button>
  );
}
