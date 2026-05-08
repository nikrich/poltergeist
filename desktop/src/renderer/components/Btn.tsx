import { useState } from 'react';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'record';
type Size = 'sm' | 'md' | 'lg';

interface Props {
  variant?: Variant;
  size?: Size;
  icon?: React.ReactNode;
  iconRight?: React.ReactNode;
  children?: React.ReactNode;
  onClick?: () => void;
  style?: React.CSSProperties;
  disabled?: boolean;
}

const sizes: Record<Size, React.CSSProperties> = {
  sm: { padding: '6px 10px', fontSize: 12, gap: 6 },
  md: { padding: '8px 14px', fontSize: 13, gap: 7 },
  lg: { padding: '11px 18px', fontSize: 14, gap: 8 },
};

const variants = (hover: boolean): Record<Variant, { bg: string; fg: string; border: string }> => ({
  primary: { bg: hover ? 'var(--neon-dark)' : 'var(--neon)', fg: '#0E0F12', border: 'transparent' },
  secondary: {
    bg: hover ? 'var(--bg-fog)' : 'var(--bg-vellum)',
    fg: 'var(--ink-0)',
    border: 'var(--hairline-2)',
  },
  ghost: { bg: hover ? 'var(--bg-vellum)' : 'transparent', fg: 'var(--ink-1)', border: 'transparent' },
  danger: {
    bg: hover ? 'rgba(255,107,90,0.20)' : 'rgba(255,107,90,0.12)',
    fg: 'var(--oxblood)',
    border: 'rgba(255,107,90,0.30)',
  },
  record: { bg: hover ? '#E8584C' : 'var(--oxblood)', fg: '#0E0F12', border: 'transparent' },
});

export function Btn({
  variant = 'primary',
  size = 'md',
  icon,
  iconRight,
  children,
  onClick,
  style,
  disabled,
}: Props) {
  const [hover, setHover] = useState(false);
  const v = variants(hover)[variant];
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        ...sizes[size],
        background: v.bg,
        color: v.fg,
        border: `1px solid ${v.border}`,
        borderRadius: 6,
        fontWeight: 500,
        fontFamily: 'var(--font-body)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        transition: 'all 120ms cubic-bezier(.2,.8,.2,1)',
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {icon}
      {children}
      {iconRight}
    </button>
  );
}
