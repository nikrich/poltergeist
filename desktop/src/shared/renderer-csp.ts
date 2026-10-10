/**
 * Content-Security-Policy for the main renderer documents (index.html and
 * index-remote-images.html). The policy is delivered as a <meta> tag because
 * the packaged renderer loads over file://, which never gets response headers
 * in Electron — so `webRequest.onHeadersReceived` cannot carry it. Instead the
 * "load remote images" setting picks which of the two HTML entries main loads;
 * a test pins each entry's meta to this function's output.
 *
 * remoteImages=false is the long-standing locked-down policy. remoteImages=true
 * adds `https:` to img-src and NOTHING else: no plain http:, no remote frames,
 * fonts, scripts, styles, media or connections.
 */
export function rendererCsp({ remoteImages }: { remoteImages: boolean }): string {
  const img = ["'self'", 'data:', 'gbasset:', 'gbdoc:', 'plugin:'];
  if (remoteImages) img.push('https:');
  return [
    "default-src 'self'",
    "script-src 'self' plugin:",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com plugin:",
    `img-src ${img.join(' ')}`,
    "connect-src 'self' gbdoc: plugin:",
    'frame-src gbproto: http://127.0.0.1:* http://localhost:*',
  ]
    .map((d) => `${d};`)
    .join(' ');
}
