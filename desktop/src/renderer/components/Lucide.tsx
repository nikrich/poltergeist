import { useEffect, useRef } from 'react';
import * as lucide from 'lucide';

interface Props {
  name: string;
  size?: number;
  color?: string;
  style?: React.CSSProperties;
  className?: string;
}

const SVG_NS = 'http://www.w3.org/2000/svg';

export function Lucide({ name, size = 16, color, style, className }: Props) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const host = ref.current;
    if (!host) return;
    const camel = name.replace(/(^|-)(\w)/g, (_, __, c: string) =>
      c.toUpperCase(),
    ) as keyof typeof lucide.icons;
    const node = lucide.icons[camel] as
      | Array<[string, Record<string, string>]>
      | undefined;
    if (!Array.isArray(node)) return;

    while (host.firstChild) host.removeChild(host.firstChild);
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('width', String(size));
    svg.setAttribute('height', String(size));
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', color ?? 'currentColor');
    svg.setAttribute('stroke-width', '1.75');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    for (const [tag, attrs] of node) {
      const child = document.createElementNS(SVG_NS, tag);
      for (const [k, v] of Object.entries(attrs)) child.setAttribute(k, v);
      svg.appendChild(child);
    }
    host.appendChild(svg);
  }, [name, size, color]);

  return (
    <span
      ref={ref}
      className={className}
      style={{
        width: size,
        height: size,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        color: color ?? 'currentColor',
        ...style,
      }}
    />
  );
}
