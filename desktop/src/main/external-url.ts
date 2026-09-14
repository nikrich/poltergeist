/**
 * Allowlist for `shell.openExternal` requests coming from the renderer.
 *
 * Only well-known external protocols are permitted so a stray markdown link
 * can't trigger `file://` or `vscode://` style handoffs. On macOS we also
 * allow the System Settings › Privacy & Security deep link, which the meeting
 * recorder uses to send the user to the Screen Recording / Microphone panes
 * after requesting capture permissions.
 */

const SYSTEM_PREFS_SECURITY_PREFIX = 'x-apple.systempreferences:com.apple.preference.security';

export function isAllowedExternalUrl(url: string, platform: NodeJS.Platform): boolean {
  if (typeof url !== 'string' || url === '') return false;
  if (/^(https?|mailto):/i.test(url)) return true;
  if (platform === 'darwin' && url.startsWith(SYSTEM_PREFS_SECURITY_PREFIX)) return true;
  return false;
}
