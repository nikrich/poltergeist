import * as icons from 'lucide-react';

interface Props {
  name: string;
  size?: number;
  color?: string;
  style?: React.CSSProperties;
  className?: string;
}

function toPascalCase(name: string): string {
  return name.replace(/(^|-)(\w)/g, (_, __, c: string) => c.toUpperCase());
}

export function Lucide({ name, size = 16, color, style, className = '' }: Props) {
  const Icon = (icons as unknown as Record<string, React.ComponentType<icons.LucideProps> | undefined>)[
    toPascalCase(name)
  ];
  if (!Icon) {
    if (import.meta.env.DEV) {
      console.warn(`Lucide: unknown icon name: "${name}"`);
    }
    return (
      <span
        className={`inline-block flex-shrink-0 ${className}`}
        style={{ width: size, height: size, ...style }}
      />
    );
  }
  return (
    <Icon
      size={size}
      color={color}
      strokeWidth={1.75}
      className={`flex-shrink-0 ${className}`}
      style={style}
    />
  );
}
