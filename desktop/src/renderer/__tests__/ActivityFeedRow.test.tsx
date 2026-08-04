import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { ActivityFeedRow } from '../components/ActivityFeedRow';

describe('ActivityFeedRow icon', () => {
  it('maps dashed sources onto underscore asset filenames', () => {
    const { container } = render(
      <ActivityFeedRow source="claude-code" verb="processed" subject="x" time="2m" />,
    );
    const img = container.querySelector('img');
    expect(img?.getAttribute('src')).toBe('assets/connectors/claude_code.svg');
  });

  it('falls back to the ghost icon when the source has no svg', () => {
    const { container } = render(
      <ActivityFeedRow source="system" verb="worker started" subject="" time="2m" />,
    );
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    fireEvent.error(img!);
    expect(container.querySelector('img')).toBeNull();
    // Lucide renders an svg element in place of the broken image
    expect(container.querySelector('svg')).not.toBeNull();
    expect(screen.getByText('worker started')).toBeInTheDocument();
  });
});
