import { describe, expect, it } from 'vitest';
import { visibleLength, wrap } from '../wrap.js';

describe('wrap', () => {
  it('wraps greedily at the width', () => {
    expect(wrap('aaa bbb ccc', 7)).toEqual(['aaa bbb', 'ccc']);
  });
  it('honours hard line breaks and keeps empty lines', () => {
    expect(wrap('one\n\ntwo', 10)).toEqual(['one', '', 'two']);
  });
  it('hard-splits words longer than the width', () => {
    expect(wrap('abcdefghij', 4)).toEqual(['abcd', 'efgh', 'ij']);
  });
  it('does not count emphasis markers toward width', () => {
    expect(visibleLength('**bold** _u_ \\*')).toBe(8);
    expect(wrap('**aaa** bbb', 7)).toEqual(['**aaa** bbb']);
  });
});
