import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { JotTree, JotList, JOT_DRAG_MIME, flattenJotTree, shortDate } from '../components/JotTree';
import type { JotTree as JotTreeData, JotTreeItem } from '../../shared/api-types';

function jot(id: string, title: string, over: Partial<JotTreeItem> = {}): JotTreeItem {
  return {
    id, title, path: `20-contexts/work/notes/${id}.md`, excerpt: '', context: 'work', project: null,
    routingStatus: 'routed', tags: [], created: '2026-05-14T09:00:00Z', updated: '2026-05-14T09:00:00Z',
    folder: null, unknownLocation: false, ...over,
  };
}

const tree: JotTreeData = {
  inbox: [jot('p1', 'pending idea', { context: null, routingStatus: 'pending', created: '2026-05-15T09:00:00Z' })],
  unrouted: [jot('u1', 'ghost jot', { context: 'gone', unknownLocation: true })],
  scopes: [
    {
      context: 'work', project: null, name: 'work', archived: false,
      folders: [{ name: 'plans', path: 'plans', folders: [], jots: [jot('j1', 'filed jot', { folder: 'plans' })] }],
      jots: [jot('j2', 'root jot', { created: '2026-05-13T09:00:00Z' })],
    },
    { context: 'work', project: 'atlas', name: 'Atlas', archived: false, folders: [], jots: [] },
  ],
};

type Call = { method: string; path: string; body: unknown };
let calls: Call[] = [];

beforeEach(() => {
  calls = [];
  window.gb.api.request = vi.fn(async (method: string, path: string, body?: unknown) => {
    calls.push({ method, path, body });
    return { ok: true, data: {} };
  }) as unknown as typeof window.gb.api.request;
});

const mutations = (method: string) => calls.filter((c) => c.method === method);
const leaf = (id: string) => JSON.stringify({ kind: 'leaf', id });
function dt(data: Record<string, string>) {
  return { getData: (k: string) => data[k] ?? '', setData: vi.fn(), types: Object.keys(data), files: [], dropEffect: 'move', effectAllowed: 'all' };
}

function renderTree(selectedId: string | null = null) {
  const onSelect = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><JotTree tree={tree} selectedId={selectedId} onSelect={onSelect} /></QueryClientProvider>);
  return onSelect;
}

describe('JotTree', () => {
  it('renders inbox, unrouted, scopes, folders and jots', () => {
    renderTree();
    expect(screen.getByTestId('jot-inbox')).toHaveTextContent('inbox');
    expect(screen.getByTestId('jot-unrouted')).toHaveTextContent('unrouted');
    expect(screen.getByText('pending idea')).toBeInTheDocument();
    expect(screen.getByText('ghost jot')).toBeInTheDocument();
    expect(screen.getByText('Atlas')).toBeInTheDocument();
    expect(screen.getByText('plans')).toBeInTheDocument();
    expect(screen.getByText('filed jot')).toBeInTheDocument();
    expect(screen.getByText('root jot')).toBeInTheDocument();
    expect(screen.queryByText('2026-05')).not.toBeInTheDocument();
  });

  it('selects a jot on click', () => {
    const onSelect = renderTree();
    fireEvent.click(screen.getByText('filed jot'));
    expect(onSelect).toHaveBeenCalledWith('j1');
  });

  it('drops an inbox jot onto a project', async () => {
    renderTree();
    fireEvent.drop(screen.getByTestId('folder-work/atlas/'), { dataTransfer: dt({ [JOT_DRAG_MIME]: leaf('p1') }) });
    await waitFor(() => expect(mutations('PATCH')).toHaveLength(1));
    expect(mutations('PATCH')[0]).toMatchObject({ path: '/v1/notes/p1/location', body: { context: 'work', project: 'atlas', folder: null } });
  });

  it('drops a jot into a folder', async () => {
    renderTree();
    fireEvent.drop(screen.getByTestId('folder-work/_/plans'), { dataTransfer: dt({ [JOT_DRAG_MIME]: leaf('j2') }) });
    await waitFor(() => expect(mutations('PATCH')).toHaveLength(1));
    expect(mutations('PATCH')[0]).toMatchObject({ path: '/v1/notes/j2/location', body: { context: 'work', project: null, folder: 'plans' } });
  });

  it('moves a folder into a project', async () => {
    renderTree();
    const ref = { context: 'work', project: null, path: 'plans' };
    fireEvent.drop(screen.getByTestId('folder-work/atlas/'), { dataTransfer: dt({ [JOT_DRAG_MIME]: JSON.stringify({ kind: 'folder', ref }) }) });
    await waitFor(() => expect(mutations('PATCH')).toHaveLength(1));
    expect(mutations('PATCH')[0]).toMatchObject({ path: '/v1/notes/folders', body: { from: ref, to: { context: 'work', project: 'atlas', path: 'plans' } } });
  });

  it('creates a folder inline', async () => {
    renderTree();
    fireEvent.click(screen.getByLabelText('new folder in work/_/'));
    const input = screen.getByPlaceholderText('folder name');
    fireEvent.change(input, { target: { value: 'q4' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(mutations('POST')).toHaveLength(1));
    expect(mutations('POST')[0]).toMatchObject({ path: '/v1/notes/folders', body: { context: 'work', project: null, path: 'q4' } });
  });

  it('deletes a folder', async () => {
    renderTree();
    fireEvent.click(screen.getByLabelText('delete work/_/plans'));
    await waitFor(() => expect(mutations('DELETE')).toHaveLength(1));
    expect(mutations('DELETE')[0]?.path).toBe('/v1/notes/folders?context=work&path=plans');
  });

  it('hides empty inbox and unrouted sections', () => {
    const qc = new QueryClient();
    render(<QueryClientProvider client={qc}><JotTree tree={{ ...tree, inbox: [], unrouted: [] }} selectedId={null} onSelect={() => {}} /></QueryClientProvider>);
    expect(screen.queryByTestId('jot-inbox')).not.toBeInTheDocument();
    expect(screen.queryByTestId('jot-unrouted')).not.toBeInTheDocument();
  });

  it('marks the selected jot active', () => {
    renderTree('j1');
    expect(screen.getByText('filed jot').closest('[role="button"]')).toHaveClass('bg-neon/12');
  });
});

describe('JotList', () => {
  it('renders flat rows and selects', () => {
    const onSelect = vi.fn();
    render(<JotList items={[jot('a', 'alpha'), jot('b', 'beta')]} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText('beta'));
    expect(onSelect).toHaveBeenCalledWith('b');
  });
});

describe('helpers', () => {
  it('flattens newest first', () => {
    expect(flattenJotTree(tree).map((j) => j.id)).toEqual(['p1', 'u1', 'j1', 'j2']);
  });

  it('formats short dates', () => {
    const now = new Date('2026-10-13T12:00:00Z');
    expect(shortDate('2026-05-14T09:00:00Z', now)).toBe('May 14');
    expect(shortDate('2025-05-14T09:00:00Z', now)).toBe('May 14, 2025');
    expect(shortDate('', now)).toBe('');
  });
});
