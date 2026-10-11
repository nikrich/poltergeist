// desktop/src/renderer/__tests__/ScopeTree.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { FolderRef } from '../../shared/api-types';
import { ScopeTree } from '../components/tree/ScopeTree';
import type { TreeDragCodec, TreeScope } from '../components/tree/tree-types';

interface Leaf { id: string; title: string; ref: FolderRef }

const MIME = 'application/x-test';
const codec: TreeDragCodec = {
  mime: MIME,
  encodeLeaf: (id) => JSON.stringify({ kind: 'leaf', id }),
  encodeFolder: (ref) => JSON.stringify({ kind: 'folder', ref }),
  decode: (raw) => { try { return JSON.parse(raw); } catch { return null; } },
};

function dt(data: Record<string, string>, files: File[] = []) {
  return { getData: (k: string) => data[k] ?? '', setData: vi.fn(), types: Object.keys(data).concat(files.length ? ['Files'] : []), files, dropEffect: 'move', effectAllowed: 'all' };
}

const P = (path: string): FolderRef => ({ context: 'work', project: 'p', path });
const leafA: Leaf = { id: 'a', title: 'Leaf A', ref: P('specs') };

function scopes(archived = false): TreeScope<Leaf>[] {
  return [{
    context: 'work', project: 'p', name: 'Proj', archived,
    leaves: [],
    folders: [
      { name: 'specs', path: 'specs', folders: [], leaves: [leafA] },
      { name: 'diagrams', path: 'diagrams', folders: [], leaves: [] },
    ],
  }];
}

function setup(over: Partial<React.ComponentProps<typeof ScopeTree<Leaf>>> = {}) {
  const props = {
    scopes: scopes(), ariaLabel: 'test tree', codec, leafId: (l: Leaf) => l.id, leafRef: (l: Leaf) => l.ref,
    renderLeaf: (l: Leaf, row: React.ComponentProps<'button'>) => <button type="button" {...row}>{l.title}</button>,
    selectedFolderKey: null, onMoveLeaf: vi.fn(), onMoveFolder: vi.fn(), onCreateFolder: vi.fn(), onRenameFolder: vi.fn(), onDeleteFolder: vi.fn(),
    ...over,
  } as React.ComponentProps<typeof ScopeTree<Leaf>>;
  const utils = render(<ScopeTree<Leaf> {...props} />);
  return { props, ...utils };
}

describe('ScopeTree', () => {
  it('renders context, project, folder and leaf', () => {
    setup();
    expect(screen.getByText('work')).toBeTruthy();
    expect(screen.getByText('Proj')).toBeTruthy();
    expect(screen.getByText('specs')).toBeTruthy();
    expect(screen.getByText('Leaf A')).toBeTruthy();
  });

  it('moves a dropped leaf into the target folder', () => {
    const { props } = setup();
    fireEvent.drop(screen.getByTestId('folder-work/p/specs'), { dataTransfer: dt({ [MIME]: codec.encodeLeaf('a') }) });
    expect(props.onMoveLeaf).toHaveBeenCalledWith('a', P('specs'));
  });

  it('moves a folder to a sibling but not into itself', () => {
    const { props } = setup();
    const specs = P('specs');
    fireEvent.drop(screen.getByTestId('folder-work/p/specs'), { dataTransfer: dt({ [MIME]: codec.encodeFolder(specs) }) });
    expect(props.onMoveFolder).not.toHaveBeenCalled();
    fireEvent.drop(screen.getByTestId('folder-work/p/diagrams'), { dataTransfer: dt({ [MIME]: codec.encodeFolder(specs) }) });
    expect(props.onMoveFolder).toHaveBeenCalledWith(specs, P('diagrams/specs'));
  });

  it('creates a folder inline and rejects names with slashes', () => {
    const { props } = setup();
    fireEvent.click(screen.getByLabelText('new folder in work/p/specs'));
    const input = screen.getByPlaceholderText('folder name');
    fireEvent.change(input, { target: { value: 'x' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(props.onCreateFolder).toHaveBeenCalledWith(P('specs/x'));
    fireEvent.click(screen.getByLabelText('new folder in work/p/specs'));
    const bad = screen.getByPlaceholderText('folder name');
    fireEvent.change(bad, { target: { value: 'a/b' } });
    fireEvent.keyDown(bad, { key: 'Enter' });
    expect(props.onCreateFolder).toHaveBeenCalledTimes(1);
  });

  it('toggles a folder when clicking its name without onSelectFolder', () => {
    setup();
    expect(screen.getByText('Leaf A')).toBeTruthy();
    fireEvent.click(screen.getByText('specs'));
    expect(screen.queryByText('Leaf A')).toBeNull();
  });

  it('calls onSelectFolder instead of toggling when provided', () => {
    const onSelectFolder = vi.fn();
    setup({ onSelectFolder });
    fireEvent.click(screen.getByText('specs'));
    expect(onSelectFolder).toHaveBeenCalledWith(P('specs'));
    expect(screen.getByText('Leaf A')).toBeTruthy();
  });

  it('treats archived scopes as read-only', () => {
    const { props } = setup({ scopes: scopes(true) });
    expect(screen.queryByLabelText('new folder in work/p/specs')).toBeNull();
    expect(screen.getByText('Leaf A').getAttribute('draggable')).toBe('false');
    fireEvent.drop(screen.getByTestId('folder-work/p/specs'), { dataTransfer: dt({ [MIME]: codec.encodeLeaf('a') }) });
    expect(props.onMoveLeaf).not.toHaveBeenCalled();
  });

  it('re-expands a collapsed folder when revealKeys changes', () => {
    const { props, rerender } = setup();
    fireEvent.click(screen.getByText('specs'));
    expect(screen.queryByText('Leaf A')).toBeNull();
    rerender(<ScopeTree<Leaf> {...props} revealKeys={['work/p/specs']} />);
    expect(screen.getByText('Leaf A')).toBeTruthy();
  });

  it('ignores dropped files when onUploadFiles is absent', () => {
    const { props } = setup();
    expect(() => fireEvent.drop(screen.getByTestId('folder-work/p/specs'), { dataTransfer: dt({}, [new File(['x'], 'a.pdf')]) })).not.toThrow();
    expect(props.onMoveLeaf).not.toHaveBeenCalled();
    expect(props.onMoveFolder).not.toHaveBeenCalled();
  });
});
