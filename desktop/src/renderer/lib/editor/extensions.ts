import { Extension } from '@tiptap/core';
import type { Extensions } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import Link from '@tiptap/extension-link';
import Table from '@tiptap/extension-table';
import TableRow from '@tiptap/extension-table-row';
import TableCell from '@tiptap/extension-table-cell';
import TableHeader from '@tiptap/extension-table-header';
import TaskList from '@tiptap/extension-task-list';
import TaskItem from '@tiptap/extension-task-item';
import { Markdown } from 'tiptap-markdown';
import { JotImage } from './image';

/**
 * tiptap-markdown's internal MarkdownTightLists extension only registers the
 * `tight` attribute on bulletList/orderedList. taskList serialisation
 * delegates to bulletList's renderList, which reads `node.attrs.tight` —
 * without the attribute, task lists serialise loose (blank line between
 * items) and fail the round-trip fixtures. This mirror extension closes the
 * gap. (Verified against the tiptap-markdown@0.8.10 dist source.)
 */
const TaskListTight = Extension.create({
  name: 'taskListTight',
  addGlobalAttributes() {
    return [
      {
        types: ['taskList'],
        attributes: {
          tight: {
            default: true,
            parseHTML: (element: HTMLElement) =>
              element.getAttribute('data-tight') === 'true' || !element.querySelector('p'),
            renderHTML: (attributes: { tight?: boolean }) => ({
              'data-tight': attributes.tight ? 'true' : null,
            }),
          },
        },
      },
    ];
  },
});

/**
 * Single source of truth for the editor schema. RichMarkdownEditor AND the
 * headless round-trip fixture tests both build from this — a fixture pass
 * therefore proves the exact schema the user types into.
 */
export function buildEditorExtensions(): Extensions {
  return [
    StarterKit,
    Link.configure({ openOnClick: false }),
    JotImage.configure({ inline: false, allowBase64: false }),
    Table.configure({ resizable: false }),
    TableRow,
    TableHeader,
    TableCell,
    TaskList,
    TaskItem.configure({ nested: true }),
    TaskListTight,
    Markdown.configure({
      html: false, // vault files are plain markdown; raw HTML is dropped
      tightLists: true,
      linkify: false,
      breaks: false,
      transformPastedText: true, // pasting markdown text parses it
      transformCopiedText: false, // copy-formatted has its own path (Task 6)
    }),
  ];
}
