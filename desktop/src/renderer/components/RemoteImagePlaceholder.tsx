/** Shown in place of a remote image the renderer CSP would block. */
export function RemoteImagePlaceholder({ alt, text }: { alt?: string | null; text: string }) {
  return (
    <span className="gb-remote-img-blocked" role="img" aria-label={alt ? `${alt} — ${text}` : text}>
      {text}
    </span>
  );
}
