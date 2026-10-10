import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AttentionPanel } from '../components/docs/AttentionPanel';
import { DocInspector } from '../components/docs/DocInspector';
import { doc } from './fixtures/library';

describe('DocInspector', () => {
  it('shows metadata and renames inline', () => {
    const onRename = vi.fn();
    render(<DocInspector doc={doc({})} scopeName="Payments" onRename={onRename} onReindex={vi.fn()} onSummarise={vi.fn()} />);
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
    render(<DocInspector doc={doc({ index_status: 'failed' })} scopeName="Payments" onRename={vi.fn()} onReindex={onReindex} onSummarise={vi.fn()} />);
    fireEvent.click(screen.getByText('retry indexing'));
    expect(onReindex).toHaveBeenCalled();
  });
});

describe('DocInspector summary card', () => {
  const base = { scopeName: 'Payments', onRename: vi.fn(), onReindex: vi.fn() };

  it('shows the summary when done', () => {
    render(<DocInspector {...base} onSummarise={vi.fn()} doc={doc({ summary: 'Defines the v2 API.', summary_state: 'done' })} />);
    expect(screen.getByText('✦ what poltergeist knows')).toBeTruthy();
    expect(screen.getByText('Defines the v2 API.')).toBeTruthy();
  });

  it('shows summarising… while pending', () => {
    render(<DocInspector {...base} onSummarise={vi.fn()} doc={doc({ summary_state: 'pending' })} />);
    expect(screen.getByText('summarising…')).toBeTruthy();
  });

  it('offers summarise when there is none, and not for opaque or failed docs', () => {
    const onSummarise = vi.fn();
    const { rerender } = render(<DocInspector {...base} onSummarise={onSummarise} doc={doc({ summary_state: 'none' })} />);
    fireEvent.click(screen.getByRole('button', { name: 'summarise' }));
    expect(onSummarise).toHaveBeenCalled();
    rerender(<DocInspector {...base} onSummarise={onSummarise} doc={doc({ kind: 'opaque', original: 'a.zip', summary_state: 'none' })} />);
    expect(screen.queryByText('✦ what poltergeist knows')).toBeNull();
    rerender(<DocInspector {...base} onSummarise={onSummarise} doc={doc({ index_status: 'failed', summary_state: 'none' })} />);
    expect(screen.queryByRole('button', { name: 'summarise' })).toBeNull();
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
