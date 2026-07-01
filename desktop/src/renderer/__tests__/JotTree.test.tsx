import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { JotTree } from '../components/JotTree';
import type { JotListItem } from '../../shared/api-types';

const items: JotListItem[] = [
  {
    id: 'manual-20260514T093015-a',
    path: '20-contexts/sanlam/notes/manual-20260514T093015-a.md',
    title: 'ascp wizard',
    excerpt: 'ascp wizard',
    context: 'sanlam',
    routingStatus: 'routed',
    tags: ['ui'],
    created: '2026-05-14T09:30:15+02:00',
    updated: '2026-05-14T09:30:15+02:00',
  },
  {
    id: 'manual-20260413T093015-b',
    path: '20-contexts/sanlam/notes/manual-20260413T093015-b.md',
    title: 'older sanlam note',
    excerpt: '',
    context: 'sanlam',
    routingStatus: 'routed',
    tags: [],
    created: '2026-04-13T09:30:15+02:00',
    updated: '2026-04-13T09:30:15+02:00',
  },
  {
    id: 'manual-20260514T100000-c',
    path: '00-inbox/raw/manual/manual-20260514T100000-c.md',
    title: 'unrouted thought',
    excerpt: '',
    context: null,
    routingStatus: 'manual_review',
    tags: [],
    created: '2026-05-14T10:00:00+02:00',
    updated: '2026-05-14T10:00:00+02:00',
  },
];

describe('JotTree', () => {
  it('groups items by context → month', () => {
    render(<JotTree items={items} selectedId={null} onSelect={() => {}} />);
    expect(screen.getByText('sanlam')).toBeInTheDocument();
    expect(screen.getByText('unrouted')).toBeInTheDocument();
    expect(screen.getAllByText('2026-05').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('2026-04')).toBeInTheDocument();
  });

  it('calls onSelect with the jot id when a leaf is clicked', () => {
    const onSelect = vi.fn();
    render(<JotTree items={items} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText('ascp wizard'));
    expect(onSelect).toHaveBeenCalledWith('manual-20260514T093015-a');
  });

  it('marks the selected leaf', () => {
    render(
      <JotTree
        items={items}
        selectedId="manual-20260514T093015-a"
        onSelect={() => {}}
      />,
    );
    const leaf = screen.getByText('ascp wizard').closest('button');
    expect(leaf?.className).toContain('bg-neon');
  });
});

// ── Project grouping ──────────────────────────────────────────────────────

function makeItem(overrides: Partial<JotListItem> & { id: string }): JotListItem {
  return {
    id: overrides.id,
    path: `20-contexts/${overrides.context ?? 'codeship'}/notes/${overrides.id}.md`,
    title: overrides.title ?? overrides.id,
    excerpt: overrides.excerpt ?? '',
    context: overrides.context ?? 'codeship',
    routingStatus: overrides.routingStatus ?? 'routed',
    tags: overrides.tags ?? [],
    created: overrides.created ?? '2026-06-01T00:00:00Z',
    updated: overrides.updated ?? '2026-06-01T00:00:00Z',
    project: overrides.project,
    thumbnail: overrides.thumbnail,
  };
}

describe('JotTree project grouping', () => {
  it('groups project jots under context → project', () => {
    const projectItems = [
      makeItem({ id: 'a', context: 'codeship', project: 'poltergeist', created: '2026-06-01T00:00:00Z' }),
      makeItem({ id: 'b', context: 'codeship', project: null, created: '2026-06-02T00:00:00Z' }),
    ];
    render(<JotTree items={projectItems} selectedId={null} onSelect={() => {}} />);
    expect(screen.getByText('poltergeist')).toBeTruthy();   // project node
    expect(screen.getByText('codeship')).toBeTruthy();      // context node
  });
});

// ── Thumbnail rendering ───────────────────────────────────────────────────────

describe('JotTree thumbnail', () => {
  it('renders an img for a jot with a thumbnail', () => {
    const thumbItems = [
      makeItem({
        id: 'thumb-jot',
        context: 'codeship',
        title: 'photo jot',
        thumbnail: '90-meta/assets/jots/2026/06/a-1.jpg',
      }),
    ];
    const { container } = render(<JotTree items={thumbItems} selectedId={null} onSelect={() => {}} />);
    // alt="" makes the role "presentation"; query the element directly
    const img = container.querySelector('img');
    expect(img).toBeTruthy();
    expect(img!.getAttribute('src')).toContain('90-meta/assets/jots/2026/06/a-1.jpg');
  });

  it('renders no img for a jot without a thumbnail', () => {
    const noThumbItems = [
      makeItem({ id: 'no-thumb', context: 'codeship', title: 'text only jot' }),
    ];
    const { container } = render(<JotTree items={noThumbItems} selectedId={null} onSelect={() => {}} />);
    expect(container.querySelector('img')).toBeNull();
  });
});
