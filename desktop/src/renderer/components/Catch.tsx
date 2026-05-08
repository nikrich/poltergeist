import { Lucide } from './Lucide';

interface Props {
  icon: string;
  text: string;
}

export function Catch({ icon, text }: Props) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 8,
        padding: '8px 6px',
        borderRadius: 4,
        fontSize: 12,
        color: 'var(--ink-0)',
        lineHeight: 1.4,
      }}
    >
      <Lucide name={icon} size={12} color="var(--neon)" style={{ marginTop: 3 }} />
      <span>{text}</span>
    </div>
  );
}
