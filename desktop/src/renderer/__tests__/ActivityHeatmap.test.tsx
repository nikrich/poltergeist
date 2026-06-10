import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import React from 'react';

import { ActivityHeatmap, indexHeatmapDays, levelFor } from '../components/ActivityHeatmap';
import type { HeatmapDay } from '../../shared/api-types';

const days: HeatmapDay[] = [
  { date: '2026-06-04', count: 23, bySource: { gmail: 9, slack: 5, system: 9 } },
  { date: '2026-06-09', count: 1, bySource: { gmail: 1 } },
];

describe('levelFor', () => {
  it('returns 0 for zero counts or zero maxCount', () => {
    expect(levelFor(0, 40)).toBe(0);
    expect(levelFor(5, 0)).toBe(0);
  });

  it('buckets counts into quartiles of maxCount', () => {
    expect(levelFor(1, 40)).toBe(1);
    expect(levelFor(10, 40)).toBe(1);
    expect(levelFor(11, 40)).toBe(2);
    expect(levelFor(20, 40)).toBe(2);
    expect(levelFor(21, 40)).toBe(3);
    expect(levelFor(30, 40)).toBe(3);
    expect(levelFor(31, 40)).toBe(4);
    expect(levelFor(40, 40)).toBe(4);
  });

  it('clamps counts above maxCount to 4', () => {
    expect(levelFor(99, 40)).toBe(4);
  });
});

describe('ActivityHeatmap', () => {
  it('renders one button per past day with an aria-label', () => {
    render(
      <ActivityHeatmap
        days={indexHeatmapDays(days)}
        weeks={2}
        maxCount={23}
        endDate="2026-06-10"
      />,
    );
    // endDate 2026-06-10 is a Wednesday → first column Jun 1–7 (7 buttons),
    // last column Jun 8–10 (3 buttons); Jun 11–14 are aria-hidden placeholders.
    expect(screen.getAllByRole('button')).toHaveLength(10);
    expect(
      screen.getByRole('button', { name: '2026-06-04 — 23 events' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '2026-06-09 — 1 event' }),
    ).toBeInTheDocument();
  });

  it('assigns intensity buckets from maxCount', () => {
    render(
      <ActivityHeatmap
        days={indexHeatmapDays(days)}
        weeks={2}
        maxCount={23}
        endDate="2026-06-10"
      />,
    );
    expect(
      screen.getByRole('button', { name: '2026-06-04 — 23 events' }),
    ).toHaveAttribute('data-level', '4');
    expect(
      screen.getByRole('button', { name: '2026-06-09 — 1 event' }),
    ).toHaveAttribute('data-level', '1');
    expect(
      screen.getByRole('button', { name: '2026-06-01 — 0 events' }),
    ).toHaveAttribute('data-level', '0');
  });

  it('fires onSelectDay with the ISO date', () => {
    const onSelectDay = vi.fn();
    render(
      <ActivityHeatmap
        days={indexHeatmapDays(days)}
        weeks={2}
        maxCount={23}
        endDate="2026-06-10"
        onSelectDay={onSelectDay}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '2026-06-04 — 23 events' }));
    expect(onSelectDay).toHaveBeenCalledWith('2026-06-04');
  });

  it('shows weekday hints in full mode and hides them in compact mode', () => {
    const { rerender } = render(
      <ActivityHeatmap days={{}} weeks={2} maxCount={0} endDate="2026-06-10" />,
    );
    expect(screen.getByText('mon')).toBeInTheDocument();
    expect(screen.getByText('wed')).toBeInTheDocument();
    expect(screen.getByText('fri')).toBeInTheDocument();
    rerender(
      <ActivityHeatmap days={{}} weeks={2} maxCount={0} endDate="2026-06-10" compact />,
    );
    expect(screen.queryByText('mon')).not.toBeInTheDocument();
  });

  it('labels the month of the first column', () => {
    render(<ActivityHeatmap days={{}} weeks={2} maxCount={0} endDate="2026-06-10" />);
    // Both columns are June → exactly one label.
    expect(screen.getByText('jun')).toBeInTheDocument();
  });
});
