import { useState } from 'react';

import type { ActivityRow } from '../../shared/api-types';
import { Lucide } from './Lucide';

interface Props {
  source: ActivityRow['source'];
  verb: ActivityRow['verb'];
  subject: ActivityRow['subject'];
  time: string;
  onClick?: () => void;
}

export function ActivityFeedRow({ source, verb, subject, time, onClick }: Props) {
  // Internal sources (system/scheduler/digest…) have no connector svg, and
  // audit sources use dashes where the asset files use underscores
  // (claude-code → claude_code.svg). Fall back to a little ghost when the
  // image can't load instead of the browser's broken-image icon.
  const [iconFailed, setIconFailed] = useState(false);
  const iconSrc = `assets/connectors/${source.replace(/-/g, '_')}.svg`;

  const className =
    'flex w-full items-center gap-[10px] rounded-sm px-[6px] py-2 text-left' +
    (onClick ? ' cursor-pointer hover:bg-paper' : '');
  const content = (
    <>
      {iconFailed ? (
        <Lucide name="ghost" size={14} className="shrink-0 text-ink-3" />
      ) : (
        <img
          src={iconSrc}
          alt=""
          className="h-[14px] w-[14px] opacity-90"
          onError={() => setIconFailed(true)}
        />
      )}
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
