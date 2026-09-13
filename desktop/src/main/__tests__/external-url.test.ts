import { describe, expect, it } from 'vitest';
import { isAllowedExternalUrl } from '../external-url';

const PRIVACY_LINK =
  'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture';

describe('isAllowedExternalUrl', () => {
  it.each(['darwin', 'win32', 'linux'] as const)('allows http(s) and mailto on %s', (platform) => {
    expect(isAllowedExternalUrl('https://example.com', platform)).toBe(true);
    expect(isAllowedExternalUrl('http://example.com', platform)).toBe(true);
    expect(isAllowedExternalUrl('HTTPS://EXAMPLE.COM', platform)).toBe(true);
    expect(isAllowedExternalUrl('mailto:someone@example.com', platform)).toBe(true);
  });

  it.each(['darwin', 'win32', 'linux'] as const)('rejects file/vscode/empty on %s', (platform) => {
    expect(isAllowedExternalUrl('file:///etc/passwd', platform)).toBe(false);
    expect(isAllowedExternalUrl('vscode://open', platform)).toBe(false);
    expect(isAllowedExternalUrl('', platform)).toBe(false);
    expect(isAllowedExternalUrl('javascript:alert(1)', platform)).toBe(false);
  });

  it('allows the Privacy & Security deep link on darwin only', () => {
    expect(isAllowedExternalUrl(PRIVACY_LINK, 'darwin')).toBe(true);
    expect(
      isAllowedExternalUrl(
        'x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone',
        'darwin',
      ),
    ).toBe(true);
    expect(isAllowedExternalUrl(PRIVACY_LINK, 'win32')).toBe(false);
    expect(isAllowedExternalUrl(PRIVACY_LINK, 'linux')).toBe(false);
  });

  it('rejects other x-apple.systempreferences panes even on darwin', () => {
    expect(
      isAllowedExternalUrl('x-apple.systempreferences:com.apple.preference.network', 'darwin'),
    ).toBe(false);
    expect(isAllowedExternalUrl('x-apple.systempreferences:', 'darwin')).toBe(false);
  });
});
