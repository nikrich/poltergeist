import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { toast } from '../stores/toast';
import { useNoteView } from '../stores/note-view';

// react-markdown's default sanitizer only lets http(s)/mailto-style schemes
// through and rewrites anything else — including our gb-note: scheme — to an
// empty href, which made wikilinks render but click dead. Pass our scheme
// through; everything else keeps the default sanitization.
const urlTransform = (url: string): string =>
  url.startsWith('gb-note:') ? url : defaultUrlTransform(url);

interface Props {
  children: string;
  className?: string;
}

// Convert Obsidian-style wikilinks into standard markdown links so
// react-markdown actually renders them. The custom `gb-note:` scheme is
// intercepted by the `a` component below to open the note in-app rather
// than as an external URL.
//
// Handles:
//   [[path/to/note]]               → [path/to/note](gb-note:path/to/note)
//   [[path/to/note|Display Title]] → [Display Title](gb-note:path/to/note)
//
// Paths inside the brackets sometimes contain `:` (e.g. `github:p` from
// older filenames) — match anything except the closing brackets so those
// pass through verbatim.
const WIKILINK_RE = /\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]/g;

function transformWikilinks(md: string): string {
  return md.replace(WIKILINK_RE, (_, path, alias) => {
    const label = (alias ?? path).trim();
    // URI-encode the path so colons and slashes survive the markdown parser.
    return `[${label}](gb-note:${encodeURIComponent(path.trim())})`;
  });
}

/** Markdown body shared by NoteView and the Capture detail panel.
 *
 * - External http/https/mailto links open in the user's browser (Electron
 *   silently blocks renderer navigations).
 * - `gb-note:<path>` links (synthesised from Obsidian-style `[[...]]`
 *   wikilinks) open the target note in the in-app NoteView.
 */
export function MarkdownBody({ children, className }: Props) {
  const openNote = useNoteView((s) => s.open);
  const source = transformWikilinks(children);
  return (
    <article className={`gb-prose ${className ?? ''}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={urlTransform}
        components={{
          a: ({ href, children, ...rest }) => {
            const onClick = async (e: React.MouseEvent<HTMLAnchorElement>) => {
              e.preventDefault();
              if (!href) return;
              if (href.startsWith('gb-note:')) {
                openNote(decodeURIComponent(href.slice('gb-note:'.length)));
                return;
              }
              const result = await window.gb.shell.openExternal(href);
              if (!result.ok) toast.error(result.error);
            };
            return (
              <a {...rest} href={href} onClick={onClick}>
                {children}
              </a>
            );
          },
        }}
      >
        {source}
      </ReactMarkdown>
    </article>
  );
}
