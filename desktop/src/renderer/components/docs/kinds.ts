import type { DocKind, DocSummary, FolderRef } from '../../../shared/api-types';

export const KIND_META: Record<DocKind, { fg: string; bg: string }> = {
  pdf: { fg: 'var(--pill-oxblood-fg)', bg: 'rgba(255,107,90,.14)' },
  image: { fg: 'var(--pill-water-fg)', bg: 'rgba(127,179,213,.14)' },
  docx: { fg: '#A9B6FF', bg: 'rgba(140,160,255,.14)' },
  xlsx: { fg: 'var(--pill-moss-fg)', bg: 'rgba(162,199,149,.14)' },
  text: { fg: 'var(--neon-ink)', bg: 'rgba(197,255,61,.12)' },
  opaque: { fg: 'var(--ink-2)', bg: 'var(--hairline)' },
};

export function kindLabel(doc: Pick<DocSummary, 'kind' | 'original'>): string {
  switch (doc.kind) {
    case 'pdf':
      return 'PDF';
    case 'image':
      return 'IMG';
    case 'docx':
      return 'DOCX';
    case 'xlsx':
      return 'XLSX';
    default: {
      const ext = doc.original.includes('.') ? doc.original.split('.').pop()!.toLowerCase() : '';
      if (ext === 'md' || ext === 'markdown') return 'MD';
      if (doc.kind === 'text') return ext ? ext.slice(0, 4).toUpperCase() : 'TXT';
      return ext ? ext.slice(0, 4).toUpperCase() : 'FILE';
    }
  }
}

export function docUrl(originalPath: string): string {
  return `gbdoc://doc/${originalPath.split('/').map(encodeURIComponent).join('/')}`;
}

export function folderKey(ref: FolderRef): string {
  return `${ref.context}/${ref.project ?? '_'}/${ref.path}`;
}

export function formatSize(bytes: number): string {
  if (bytes < 1000) return `${bytes} B`;
  if (bytes < 1_000_000) return `${(bytes / 1000).toFixed(0)} KB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

export function vaultAbs(vaultPath: string, rel: string): string {
  return `${vaultPath.replace(/[\\/]+$/, '')}/${rel}`;
}
