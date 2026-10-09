import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../components/docs/pdf', () => ({ renderThumb: vi.fn(async () => {}), cancelRender: vi.fn(), loadPdf: vi.fn() }));

import { FolderView } from '../components/docs/FolderView';
import { findFolder } from '../components/docs/tree-model';
import { useDocs } from '../stores/docs';
import { libraryFixture } from './fixtures/library';

const ref = { context: 'work', project: 'payments', path: '' };

function setup(uploads = useDocs.getState().uploads) {
  const props = {
    refKey: 'work/payments/', folderRef: ref, node: findFolder(libraryFixture(), ref)!, archived: false, uploads,
    selectedDocId: null, onSelectDoc: vi.fn(), onOpenDoc: vi.fn(), onOpenFolder: vi.fn(), onUploadFiles: vi.fn(), onNewFolder: vi.fn(),
  };
  render(<FolderView {...props} />);
  return props;
}

describe('FolderView', () => {
  beforeEach(() => {
    // Node 25 ships a bare global localStorage that shadows jsdom's; use a stub.
    const mem = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => mem.get(k) ?? null,
      setItem: (k: string, v: string) => void mem.set(k, v),
      removeItem: (k: string) => void mem.delete(k),
      clear: () => mem.clear(),
    });
    localStorage.clear();
    useDocs.setState({ viewModes: {}, uploads: [] });
  });

  it('lists subfolders and docs, opens on double click', () => {
    const p = setup();
    expect(screen.getByText('diagrams')).toBeTruthy();
    fireEvent.click(screen.getByText('Rate card Q4'));
    expect(p.onSelectDoc).toHaveBeenCalledWith('cccccccccccc');
    fireEvent.doubleClick(screen.getByText('Rate card Q4'));
    expect(p.onOpenDoc).toHaveBeenCalledWith('cccccccccccc');
    fireEvent.doubleClick(screen.getByText('diagrams'));
    expect(p.onOpenFolder).toHaveBeenCalledWith({ ...ref, path: 'diagrams' });
  });

  it('switches to grid and remembers it per folder', () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: /grid/ }));
    expect(screen.getAllByTestId('doc-card')).toHaveLength(1);
    expect(useDocs.getState().viewMode('work/payments/')).toBe('grid');
  });

  it('shows upload ghosts with errors', () => {
    setup([
      { id: 'u1', name: 'Ledger ERD.png', size: 4_800_000, key: 'work/payments/', status: 'uploading' },
      { id: 'u2', name: 'huge.zip', size: 30_000_000, key: 'work/payments/', status: 'error', error: 'too large (max 20 MB)' },
    ]);
    expect(screen.getByText('Ledger ERD.png')).toBeTruthy();
    expect(screen.getByText('too large (max 20 MB)')).toBeTruthy();
  });

  it('uploads files dropped on the pane into this folder', () => {
    const p = setup();
    const f = new File(['x'], 'a.pdf');
    fireEvent.drop(screen.getByTestId('folder-view'), { dataTransfer: { files: [f], getData: () => '', types: ['Files'] } });
    expect(p.onUploadFiles).toHaveBeenCalledWith([f], ref);
  });

  it('ignores OS file drops on an archived folder', () => {
    const props = {
      refKey: 'work/payments/', folderRef: ref, node: findFolder(libraryFixture(), ref)!, archived: true, uploads: [],
      selectedDocId: null, onSelectDoc: vi.fn(), onOpenDoc: vi.fn(), onOpenFolder: vi.fn(), onUploadFiles: vi.fn(), onNewFolder: vi.fn(),
    };
    render(<FolderView {...props} />);
    const f = new File(['x'], 'a.pdf');
    fireEvent.drop(screen.getByTestId('folder-view'), { dataTransfer: { files: [f], getData: () => '', types: ['Files'] } });
    expect(props.onUploadFiles).not.toHaveBeenCalled();
  });

  it('ignores internal doc drags that carry no files', () => {
    const p = setup();
    fireEvent.drop(screen.getByTestId('folder-view'), { dataTransfer: { files: [], getData: () => '', types: ['application/x-gb-library'] } });
    expect(p.onUploadFiles).not.toHaveBeenCalled();
  });

  it('keeps view mode per folder', () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: /grid/ }));
    expect(useDocs.getState().viewMode('work/payments/')).toBe('grid');
    expect(useDocs.getState().viewMode('work/_/specs')).toBe('list');
  });
});
