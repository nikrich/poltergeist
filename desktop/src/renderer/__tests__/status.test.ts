import { describe, it, expect, vi } from 'vitest';
import { codeSpan, parseStatusText, sanitizeStatusLabel, statusMarkdown } from '../lib/editor/status';
import { onGb } from '../lib/editor/events';
import { findNodePos, makeEditor, markdownOf } from './helpers/editor';

describe('parseStatusText', () => {
  it('parses label and colour', () => {
    expect(parseStatusText('status:In progress/yellow')).toEqual({ label: 'In progress', color: 'yellow' });
  });
  it('keeps colour null when the suffix is absent or unknown', () => {
    expect(parseStatusText('status:Blocked')).toEqual({ label: 'Blocked', color: null });
    expect(parseStatusText('status:a/orange')).toEqual({ label: 'a/orange', color: null });
  });
  it('rejects non-status and empty labels', () => {
    expect(parseStatusText('route_event')).toBeNull();
    expect(parseStatusText('status:')).toBeNull();
    expect(parseStatusText('status:/red')).toBeNull();
  });
});

describe('codeSpan / statusMarkdown', () => {
  it('uses a fence longer than any backtick run inside', () => {
    expect(codeSpan('status:x/red')).toBe('`status:x/red`');
    expect(codeSpan('status:a`b/red')).toBe('``status:a`b/red``');
    expect(codeSpan('status:a`')).toBe('`` status:a` ``');
  });
  it('omits the colour suffix when colour is null', () => {
    expect(statusMarkdown({ label: 'Blocked', color: null })).toBe('`status:Blocked`');
    expect(statusMarkdown({ label: 'Done', color: 'green' })).toBe('`status:Done/green`');
  });
  it('sanitizeStatusLabel strips newlines and trims', () => {
    expect(sanitizeStatusLabel('  Done \n now ')).toBe('Done now');
  });
});

describe('status node', () => {
  it('parses status code spans into status atoms; other code stays a mark', () => {
    const editor = makeEditor('a `status:Done/green` b `route_event`');
    const json = JSON.stringify(editor.getJSON());
    expect(json).toContain('"type":"status"');
    expect(json).toContain('"label":"Done"');
    expect(json).toContain('"type":"code"');
  });

  it('does not touch status-like text inside fenced code', () => {
    const editor = makeEditor('```\n`status:x/red`\n```');
    expect(JSON.stringify(editor.getJSON())).not.toContain('"type":"status"');
  });

  it('insertStatus and updateStatusAt write markdown', () => {
    const editor = makeEditor('x');
    editor.commands.setTextSelection(2);
    editor.commands.insertStatus({ label: 'To do', color: 'grey' });
    expect(markdownOf(editor)).toBe('x`status:To do/grey`');
    const pos = findNodePos(editor, (n) => n.type.name === 'status');
    expect(editor.commands.updateStatusAt(pos, { label: 'Done', color: 'green' })).toBe(true);
    expect(markdownOf(editor)).toBe('x`status:Done/green`');
  });

  it('updateStatusAt refuses a position that is not a status', () => {
    const editor = makeEditor('plain');
    expect(editor.commands.updateStatusAt(0, { label: 'x' })).toBe(false);
  });

  it('clicking a status emits gb:status:edit with its position (editable only)', () => {
    const editor = makeEditor('a `status:Done/green`');
    const spy = vi.fn();
    const off = onGb(editor, 'gb:status:edit', spy);
    const pos = findNodePos(editor, (n) => n.type.name === 'status');
    const node = editor.state.doc.nodeAt(pos)!;
    const view = editor.view;
    const handled = view.someProp('handleClickOn', (f) =>
      f(view, pos + 1, node, pos, new MouseEvent('click'), true),
    );
    expect(handled).toBe(true);
    expect(spy).toHaveBeenCalledWith({ pos });
    off();

    const ro = makeEditor('a `status:Done/green`', false);
    const roPos = findNodePos(ro, (n) => n.type.name === 'status');
    const roHandled = ro.view.someProp('handleClickOn', (f) =>
      f(ro.view, roPos + 1, ro.state.doc.nodeAt(roPos)!, roPos, new MouseEvent('click'), true),
    );
    expect(roHandled).toBeFalsy();
  });
});
