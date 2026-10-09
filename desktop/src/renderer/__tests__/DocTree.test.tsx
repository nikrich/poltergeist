// desktop/src/renderer/__tests__/DocTree.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DocTree } from '../components/docs/DocTree';
import { DRAG_MIME, encodeDrag } from '../components/docs/tree-model';
import { doc, libraryFixture } from './fixtures/library';

function dt(data: Record<string, string>, files: File[] = []) {
  return { getData: (k: string) => data[k] ?? '', setData: vi.fn(), types: Object.keys(data).concat(files.length ? ['Files'] : []), files, dropEffect: 'move', effectAllowed: 'all' };
}

function setup(over: Partial<React.ComponentProps<typeof DocTree>> = {}) {
  const props = {
    tree: libraryFixture(), selection: null, onSelect: vi.fn(), onMoveDoc: vi.fn(), onMoveFolder: vi.fn(),
    onUploadFiles: vi.fn(), onCreateFolder: vi.fn(), onRenameFolder: vi.fn(), onDeleteFolder: vi.fn(), ...over,
  };
  render(<DocTree {...props} />);
  return props;
}

describe('DocTree', () => {
  it('renders contexts, projects with counts, folders and kind chips', () => {
    setup();
    expect(screen.getByText('work')).toBeTruthy();
    expect(screen.getByText('Payments')).toBeTruthy();
    expect(screen.getByTestId('count-work/payments/')).toHaveTextContent('3');
    expect(screen.getByText('specs')).toBeTruthy();
    expect(screen.getByText('Payments API v2')).toBeTruthy();
    expect(screen.getAllByText('PDF').length).toBeGreaterThan(0);
  });

  it('selects folders and docs', () => {
    const p = setup();
    fireEvent.click(screen.getByText('specs'));
    expect(p.onSelect).toHaveBeenCalledWith({ type: 'folder', ref: { context: 'work', project: 'payments', path: 'specs' } });
    fireEvent.click(screen.getByText('Payments API v2'));
    expect(p.onSelect).toHaveBeenCalledWith({ type: 'doc', docId: 'aaaaaaaaaaaa' });
  });

  it('moves a dropped doc into the target folder, across projects too', () => {
    const p = setup();
    const target = screen.getByTestId('folder-work/_/');
    fireEvent.dragOver(target, { dataTransfer: dt({ [DRAG_MIME]: '' }) });
    expect(target.className).toContain('outline-dashed');
    fireEvent.drop(target, { dataTransfer: dt({ [DRAG_MIME]: encodeDrag({ type: 'doc', docId: 'aaaaaaaaaaaa' }) }) });
    expect(p.onMoveDoc).toHaveBeenCalledWith('aaaaaaaaaaaa', { context: 'work', project: null, path: '' });
  });

  it('moves a folder under another, refusing to drop into itself', () => {
    const p = setup();
    const specs = { context: 'work', project: 'payments', path: 'specs' };
    fireEvent.drop(screen.getByTestId('folder-work/payments/diagrams'), { dataTransfer: dt({ [DRAG_MIME]: encodeDrag({ type: 'folder', ref: specs }) }) });
    expect(p.onMoveFolder).toHaveBeenCalledWith(specs, { context: 'work', project: 'payments', path: 'diagrams/specs' });
    fireEvent.drop(screen.getByTestId('folder-work/payments/specs'), { dataTransfer: dt({ [DRAG_MIME]: encodeDrag({ type: 'folder', ref: specs }) }) });
    expect(p.onMoveFolder).toHaveBeenCalledTimes(1);
  });

  it('uploads OS files dropped on a folder', () => {
    const p = setup();
    const f = new File(['x'], 'a.pdf');
    fireEvent.drop(screen.getByTestId('folder-work/payments/specs'), { dataTransfer: dt({}, [f]) });
    expect(p.onUploadFiles).toHaveBeenCalledWith([f], { context: 'work', project: 'payments', path: 'specs' });
  });

  it('creates a subfolder inline', () => {
    const p = setup();
    fireEvent.click(screen.getByLabelText('new folder in work/payments/specs'));
    const input = screen.getByPlaceholderText('folder name');
    fireEvent.change(input, { target: { value: 'v2' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(p.onCreateFolder).toHaveBeenCalledWith({ context: 'work', project: 'payments', path: 'specs/v2' });
  });

  it('shows the needs-attention row only when there are items', () => {
    const tree = libraryFixture();
    tree.attention = [{ kind: 'orphan_note', context: 'work', project: null, folder: '', name: 'x.md', doc_id: 'dddddddddddd' }];
    const p = setup({ tree });
    fireEvent.click(screen.getByText('needs attention'));
    expect(p.onSelect).toHaveBeenCalledWith({ type: 'attention' });
  });

  it('drops on a doc row resolve to its containing folder', () => {
    const p = setup();
    const row = screen.getByText('Payments API v2').closest('button')!;
    fireEvent.drop(row, { dataTransfer: dt({ [DRAG_MIME]: encodeDrag({ type: 'doc', docId: 'bbbbbbbbbbbb' }) }) });
    expect(p.onMoveDoc).toHaveBeenCalledWith('bbbbbbbbbbbb', { context: 'work', project: 'payments', path: 'specs' });
    const f = new File(['x'], 'a.pdf');
    fireEvent.drop(row, { dataTransfer: dt({}, [f]) });
    expect(p.onUploadFiles).toHaveBeenCalledWith([f], { context: 'work', project: 'payments', path: 'specs' });
  });

  it('treats archived scopes as read-only', () => {
    const tree = libraryFixture();
    tree.scopes.push({
      context: 'work', project: 'old', name: 'Old', archived: true,
      docs: [doc({ doc_id: 'eeeeeeeeeeee', title: 'Old doc', project: 'old', folder: '' })],
      folders: [{ name: 'arch', path: 'arch', folders: [], docs: [] }],
    });
    const p = setup({ tree });
    fireEvent.drop(screen.getByTestId('folder-work/old/'), { dataTransfer: dt({ [DRAG_MIME]: encodeDrag({ type: 'doc', docId: 'aaaaaaaaaaaa' }) }) });
    expect(p.onMoveDoc).not.toHaveBeenCalled();
    expect(screen.getByTestId('folder-work/old/arch').getAttribute('draggable')).toBe('false');
    expect(screen.getByText('Old doc').closest('button')!.getAttribute('draggable')).toBe('false');
    expect(screen.queryByLabelText('new folder in work/old/')).toBeNull();
    expect(screen.queryByLabelText('new folder in work/old/arch')).toBeNull();
  });

  it('rejects folder names with slashes or leading dots', () => {
    const p = setup();
    fireEvent.click(screen.getByLabelText('new folder in work/payments/specs'));
    const input = screen.getByPlaceholderText('folder name');
    fireEvent.change(input, { target: { value: 'a/b' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(p.onCreateFolder).not.toHaveBeenCalled();
  });
});
