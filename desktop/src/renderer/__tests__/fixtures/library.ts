// desktop/src/renderer/__tests__/fixtures/library.ts
import type { DocSummary, LibraryTree } from '../../../shared/api-types';

export function doc(over: Partial<DocSummary>): DocSummary {
  return {
    doc_id: 'aaaaaaaaaaaa', title: 'Payments API v2', kind: 'pdf', mime: 'application/pdf',
    size: 2_150_331, created: '2026-10-07T10:00:00+00:00', context: 'work', project: 'payments',
    folder: 'specs', original: 'Payments API v2.pdf',
    original_path: '20-contexts/work/projects/payments/docs/specs/Payments API v2.pdf',
    note_path: '20-contexts/work/projects/payments/docs/specs/payments-api-v2-aaaaaa.md',
    index_status: 'ok', pages: 24, excerpt: 'Idempotency keys required on POST.', ...over,
  };
}

export function libraryFixture(): LibraryTree {
  return {
    scopes: [
      { context: 'work', project: null, name: 'unfiled', archived: false, folders: [], docs: [] },
      {
        context: 'work', project: 'payments', name: 'Payments', archived: false,
        docs: [doc({ doc_id: 'cccccccccccc', title: 'Rate card Q4', kind: 'xlsx', folder: '', original: 'Rate card Q4.xlsx', original_path: '20-contexts/work/projects/payments/docs/Rate card Q4.xlsx' })],
        folders: [
          { name: 'diagrams', path: 'diagrams', folders: [], docs: [doc({ doc_id: 'bbbbbbbbbbbb', title: 'Settlement flow', kind: 'image', folder: 'diagrams', original: 'Settlement flow.png', original_path: '20-contexts/work/projects/payments/docs/diagrams/Settlement flow.png', pages: null })] },
          { name: 'specs', path: 'specs', folders: [], docs: [doc({})] },
        ],
      },
      { context: 'personal', project: null, name: 'unfiled', archived: false, folders: [], docs: [] },
    ],
    attention: [],
  };
}
