import { REMOTE_IMAGE_BLOCKED_TEXT } from '../lib/remote-images';

/** Shown in place of a remote image the renderer CSP would block. */
export function RemoteImagePlaceholder({ alt }: { alt?: string | null }) {
  return (
    <span
      className="gb-remote-img-blocked"
      role="img"
      aria-label={alt ? `${alt} — ${REMOTE_IMAGE_BLOCKED_TEXT}` : REMOTE_IMAGE_BLOCKED_TEXT}
    >
      {REMOTE_IMAGE_BLOCKED_TEXT}
    </span>
  );
}
