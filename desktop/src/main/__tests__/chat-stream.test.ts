import { describe, expect, it } from 'vitest';
import { createSseParser } from '../chat-stream';

describe('createSseParser', () => {
  it('extracts data payloads from complete blocks', () => {
    const parse = createSseParser();
    expect(parse('data: {"type":"delta"}\n\n')).toEqual(['{"type":"delta"}']);
  });

  it('buffers partial blocks across chunks', () => {
    const parse = createSseParser();
    expect(parse('data: {"a"')).toEqual([]);
    expect(parse(':1}\n')).toEqual([]);
    expect(parse('\ndata: {"b":2}\n\n')).toEqual(['{"a":1}', '{"b":2}']);
  });

  it('handles multiple events in one chunk', () => {
    const parse = createSseParser();
    expect(parse('data: 1\n\ndata: 2\n\n')).toEqual(['1', '2']);
  });

  it('ignores non-data lines and comments', () => {
    const parse = createSseParser();
    expect(parse(': keepalive\nevent: x\ndata: 3\n\n')).toEqual(['3']);
  });
});
