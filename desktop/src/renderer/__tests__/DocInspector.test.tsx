import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AttentionPanel } from '../components/docs/AttentionPanel';
import { DocInspector } from '../components/docs/DocInspector';
import { doc } from './fixtures/library';

describe('DocInspector', () => {
  it('shows metadata and renames inline', () => {
    const onRename = vi.fn();
    render(<DocInspector doc={doc({})} scopeName="Payments" onRename={onRename} onReindex={vi.fn()} />);
    expect(screen.getByText('PDF · 24 pages')).toBeTruthy();
    expect(screen.getByText('2.2 MB')).toBeTruthy();
    expect(screen.getByText('Payments')).toBeTruthy();
    fireEvent.click(screen.getByText('Payments API v2'));
    const input = screen.getByDisplayValue('Payments API v2');
    fireEvent.change(input, { target: { value: 'Payments API v3' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onRename).toHaveBeenCalledWith('Payments API v3');
  });

  it('offers retry when indexing failed', () => {
    const onReindex = vi.fn();
    render(<DocInspector doc={doc({ index_status: 'failed' })} scopeName="Payments" onRename={vi.fn()} onReindex={onReindex} />);
    fireEvent.click(screen.getByText('retry indexing'));
    expect(onReindex).toHaveBeenCalled();
  });
});

describe('AttentionPanel', () => {
  it('maps each item kind to its repair action', () => {
    const p = { onAdopt: vi.fn(), onRemoveOrphan: vi.fn(), onReindex: vi.fn() };
    render(
      <AttentionPanel
        items={[
          { kind: 'unclaimed_original', context: 'work', project: null, folder: 'inbox', name: 'x.pdf', doc_id: null },
          { kind: 'orphan_note', context: 'work', project: null, folder: '', name: 'y-abc.md', doc_id: 'dddddddddddd' },
          { kind: 'index_failed', context: 'work', project: 'payments', folder: '', name: 'z.pdf', doc_id: 'eeeeeeeeeeee' },
        ]}
        {...p}
      />,
    );
    fireEvent.click(screen.getByText('add to library'));
    expect(p.onAdopt).toHaveBeenCalledWith(expect.objectContaining({ name: 'x.pdf' }));
    fireEvent.click(screen.getByText('remove note'));
    expect(p.onRemoveOrphan).toHaveBeenCalledWith('dddddddddddd');
    fireEvent.click(screen.getByText('retry'));
    expect(p.onReindex).toHaveBeenCalledWith('eeeeeeeeeeee');
  });
});
