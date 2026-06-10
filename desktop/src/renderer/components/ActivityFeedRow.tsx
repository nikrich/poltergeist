import type { ActivityRow } from '../../shared/api-types';

interface Props {
  source: ActivityRow['source'];
  verb: ActivityRow['verb'];
  subject: ActivityRow['subject'];
  time: string;
  onClick?: () => void;
}

export function ActivityFeedRow({ source, verb, subject, time, onClick }: Props) {
  const className =
    'flex w-full items-center gap-[10px] rounded-sm px-[6px] py-2 text-left' +
    (onClick ? ' cursor-pointer hover:bg-paper' : '');
  const content = (
    <>
      <img
        src={`assets/connectors/${source}.svg`}
        alt=""
        className="h-[14px] w-[14px] opacity-90"
      />
      <span className="font-mono text-10 text-ink-2">{verb}</span>
      <span className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-12 text-ink-0">
        {subject}
      </span>
      <span className="font-mono text-10 text-ink-3">{time}</span>
    </>
  );
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={className}>
        {content}
      </button>
    );
  }
  return <div className={className}>{content}</div>;
}
