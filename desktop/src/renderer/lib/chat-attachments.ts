import { post } from './api/client';
import type { ChatAttachment } from '../../shared/api-types';

export const MAX_FILE_BYTES = 1_000_000;
export const MAX_DOC_BYTES = 20_000_000;
export const MAX_FILES = 10;

const DOCX_MIME =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const DOC_EXTENSIONS = ['pdf', 'docx', 'png', 'jpg', 'jpeg', 'gif', 'webp'];

// Mirror the sidecar's TEXT_EXTENSIONS (chat_attachments.py) for this slice.
export const ACCEPTED_EXTENSIONS = [
  'md', 'markdown', 'txt', 'text', 'log', 'csv', 'tsv', 'json', 'yaml', 'yml',
  'py', 'js', 'ts', 'tsx', 'jsx', 'go', 'rs', 'java', 'c', 'h', 'cpp', 'sh',
  'rb', 'sql', 'html', 'css', 'xml', 'toml', 'ini',
  'pdf', 'docx',
  'png', 'jpg', 'jpeg', 'gif', 'webp',
];

function extOf(file: File): string {
  return file.name.split('.').pop()?.toLowerCase() ?? '';
}

export function isAccepted(file: File): boolean {
  const ext = extOf(file);
  return (
    ACCEPTED_EXTENSIONS.includes(ext) ||
    file.type.startsWith('text/') ||
    file.type.startsWith('image/') ||
    file.type === 'application/pdf' ||
    file.type === DOCX_MIME
  );
}

export function maxBytesFor(file: File): number {
  const large =
    DOC_EXTENSIONS.includes(extOf(file)) ||
    file.type.startsWith('image/') ||
    file.type === 'application/pdf' ||
    file.type === DOCX_MIME;
  return large ? MAX_DOC_BYTES : MAX_FILE_BYTES;
}

export async function fileToBase64(file: File): Promise<string> {
  // FileReader.readAsDataURL rather than file.arrayBuffer(): the latter is
  // unsupported by jsdom's File/Blob shim used in the test environment, and
  // FileReader works identically in real Chromium (Electron renderer).
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const commaIndex = result.indexOf(',');
      resolve(commaIndex >= 0 ? result.slice(commaIndex + 1) : result);
    };
    reader.onerror = () => reject(reader.error ?? new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });
}

export async function uploadAttachments(
  convId: string,
  files: File[],
): Promise<ChatAttachment[]> {
  const payload = {
    files: await Promise.all(
      files.map(async (f) => ({
        name: f.name,
        mime: f.type,
        content_b64: await fileToBase64(f),
      })),
    ),
  };
  const res = await post<{ attachments: ChatAttachment[] }>(
    `/v1/chat/${convId}/attachments`,
    payload,
  );
  return res.attachments;
}
