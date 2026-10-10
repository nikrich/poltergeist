import { afterEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { rendererCsp } from '../../shared/renderer-csp';
import {
  INSECURE_IMAGE_BLOCKED_TEXT,
  REMOTE_IMAGE_BLOCKED_TEXT,
  blockedRemoteImageText,
  isLocalImageSrc,
  remoteImagesAllowed,
} from '../lib/remote-images';
import { MarkdownBody } from '../components/MarkdownBody';
import { makeEditor } from './helpers/editor';

function installCsp(remoteImages: boolean): void {
  const meta = document.createElement('meta');
  meta.setAttribute('http-equiv', 'Content-Security-Policy');
  meta.setAttribute('content', rendererCsp({ remoteImages }));
  meta.dataset.testCsp = '';
  document.head.append(meta);
}

afterEach(() => {
  document.head.querySelectorAll('meta[data-test-csp]').forEach((m) => m.remove());
});

describe('isLocalImageSrc (fail-closed allowlist)', () => {
  const local = [
    'gbasset://asset/x.jpg',
    'GBASSET://asset/x.jpg',
    'gbdoc://doc/x.png',
    'plugin://p/icon.png',
    'data:image/png;base64,AAAA',
    'DATA:IMAGE/png;base64,AAAA',
    '90-meta/assets/x.jpg',
    './x.png',
    '/abs/x.png',
    '', // nothing to load
  ];
  const remote = [
    'https://example.com/a.png',
    'HTTPS://example.com/a.png',
    'http://example.com/a.png',
    'http:example.com/a.png',
    '//example.com/a.png',
    '\\\\host\\share\\a.png',
    '/\\example.com/a.png',
    '\\/example.com/a.png',
    '  https://example.com/a.png',
    '\u0001https://example.com/a.png',
    'ht\ttps://example.com/a.png',
    'ht\nttps://example.com/a.png',
    '&#104;ttps://example.com/a.png',
    'https&colon;//example.com/a.png',
    'ftp://example.com/a.png',
    'file:///etc/passwd',
    'data:text/html,<b>x</b>',
    'javascript:alert(1)',
    'blob:https://example.com/x',
    'c:\\\\x.png',
  ];
  for (const src of local) it(`local: ${JSON.stringify(src)}`, () => expect(isLocalImageSrc(src)).toBe(true));
  for (const src of remote) it(`not local: ${JSON.stringify(src)}`, () => expect(isLocalImageSrc(src)).toBe(false));
});

describe('blockedRemoteImageText', () => {
  it('blocks every non-local src while the setting is off', () => {
    installCsp(false);
    for (const src of ['https://x.test/a.png', 'HTTPS://x.test/a.png', '//x.test/a.png', ' \u0000https://x.test/a.png', 'ftp://x.test/a'])
      expect(blockedRemoteImageText(src)).toBe(REMOTE_IMAGE_BLOCKED_TEXT);
  });

  it('allows only https (any case, after normalisation) while the setting is on', () => {
    installCsp(true);
    expect(blockedRemoteImageText('https://x.test/a.png')).toBeNull();
    expect(blockedRemoteImageText('HTTPS://x.test/a.png')).toBeNull();
    for (const src of ['http://x.test/a.png', '//x.test/a.png', 'ftp://x.test/a', 'file:///etc/passwd'])
      expect(blockedRemoteImageText(src)).toBe(INSECURE_IMAGE_BLOCKED_TEXT);
  });

  it('never blocks local sources', () => {
    installCsp(false);
    for (const src of ['gbasset://asset/x.jpg', 'data:image/png;base64,AAAA', '90-meta/a.jpg'])
      expect(blockedRemoteImageText(src)).toBeNull();
  });
});

describe('remoteImagesAllowed', () => {
  it('is false with no policy, and with the default policy', () => {
    expect(remoteImagesAllowed()).toBe(false);
    installCsp(false);
    expect(remoteImagesAllowed()).toBe(false);
  });

  it('is true when the document policy allows https images', () => {
    installCsp(true);
    expect(remoteImagesAllowed()).toBe(true);
  });
});

describe('MarkdownBody remote images', () => {
  it('shows a placeholder instead of requesting a remote image when blocked', () => {
    installCsp(false);
    const { container } = render(<MarkdownBody>{'![chart](https://example.com/c.png)'}</MarkdownBody>);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText(REMOTE_IMAGE_BLOCKED_TEXT)).toBeInTheDocument();
  });

  it('blocks plain http images too', () => {
    installCsp(false);
    const { container } = render(<MarkdownBody>{'![x](http://example.com/c.png)'}</MarkdownBody>);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText(REMOTE_IMAGE_BLOCKED_TEXT)).toBeInTheDocument();
  });

  it('renders the remote image when the policy allows it', () => {
    installCsp(true);
    const { container } = render(<MarkdownBody>{'![chart](https://example.com/c.png)'}</MarkdownBody>);
    expect(container.querySelector('img')?.getAttribute('src')).toBe('https://example.com/c.png');
    expect(screen.queryByText(REMOTE_IMAGE_BLOCKED_TEXT)).toBeNull();
  });

  it('still blocks plain http images when https images are allowed', () => {
    installCsp(true);
    const { container } = render(<MarkdownBody>{'![x](http://example.com/c.png)'}</MarkdownBody>);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText(INSECURE_IMAGE_BLOCKED_TEXT)).toBeInTheDocument();
  });

  it('renders no element for raw HTML images, srcset or <picture> sources', () => {
    installCsp(true);
    const { container } = render(
      <MarkdownBody>
        {'<img src="https://example.com/a.png" srcset="https://example.com/b.png 2x">\n\n<picture><source srcset="https://example.com/c.png"><img src="https://example.com/d.png"></picture>\n\n<div style="background-image:url(https://example.com/e.png)">x</div>'}
      </MarkdownBody>,
    );
    // react-markdown has no rehype-raw: raw HTML stays inert escaped text.
    expect(container.querySelector('img, source, picture, [srcset], [style]')).toBeNull();
  });

  it('blocks entity-encoded and mixed-case remote srcs while off', () => {
    installCsp(false);
    const { container } = render(
      <MarkdownBody>{'![a](&#104;ttps://example.com/a.png) ![b](HTTPS://example.com/b.png)'}</MarkdownBody>,
    );
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getAllByText(REMOTE_IMAGE_BLOCKED_TEXT)).toHaveLength(2);
  });

  it('leaves data: images alone', () => {
    installCsp(false);
    const { container } = render(
      <MarkdownBody>{'![dot](data:image/png;base64,AAAA)'}</MarkdownBody>,
    );
    expect(screen.queryByText(REMOTE_IMAGE_BLOCKED_TEXT)).toBeNull();
    expect(container.querySelector('img')).not.toBeNull();
  });
});

describe('editor image node remote images', () => {
  it('shows a placeholder and no <img> for a remote src when blocked', () => {
    installCsp(false);
    const editor = makeEditor('![chart](https://example.com/c.png)');
    expect(editor.view.dom.querySelector('img')).toBeNull();
    expect(editor.view.dom.textContent).toContain(REMOTE_IMAGE_BLOCKED_TEXT);
  });

  it('keeps the remote src in the markdown when blocked', () => {
    installCsp(false);
    const editor = makeEditor('![chart](https://example.com/c.png)');
    expect(editor.getJSON().content?.[0]).toMatchObject({
      type: 'image',
      attrs: { src: 'https://example.com/c.png' },
    });
  });

  it('renders the remote image when the policy allows it', () => {
    installCsp(true);
    const editor = makeEditor('![chart](https://example.com/c.png)');
    const img = editor.view.dom.querySelector<HTMLImageElement>('img.gb-jot-img');
    expect(img?.getAttribute('src')).toBe('https://example.com/c.png');
    expect(editor.view.dom.textContent).not.toContain(REMOTE_IMAGE_BLOCKED_TEXT);
  });

  it('still blocks plain http images when https images are allowed', () => {
    installCsp(true);
    const editor = makeEditor('![x](http://example.com/c.png)');
    expect(editor.view.dom.querySelector('img')).toBeNull();
    expect(editor.view.dom.textContent).toContain(INSECURE_IMAGE_BLOCKED_TEXT);
  });

  it('drops raw HTML images (no img, srcset or remote URL in the DOM)', () => {
    installCsp(true);
    const editor = makeEditor(
      '<img src="https://example.com/a.png" srcset="https://example.com/b.png 2x">\n\n<picture><source srcset="https://example.com/c.png"></picture>',
    );
    expect(editor.view.dom.querySelector('img, source, [srcset]')).toBeNull();
  });

  it('blocks a protocol-relative src while off', () => {
    installCsp(false);
    const editor = makeEditor('![a](//example.com/a.png)');
    expect(editor.view.dom.querySelector('img')).toBeNull();
    expect(editor.view.dom.textContent).toContain(REMOTE_IMAGE_BLOCKED_TEXT);
  });

  it('vault and gbasset images still render when remote images are blocked', () => {
    installCsp(false);
    const editor = makeEditor('![a](90-meta/assets/x.jpg)\n\n![b](gbasset://asset/y.jpg)');
    const srcs = [...editor.view.dom.querySelectorAll('img.gb-jot-img')].map((i) =>
      i.getAttribute('src'),
    );
    expect(srcs).toEqual(['gbasset://asset/90-meta/assets/x.jpg', 'gbasset://asset/y.jpg']);
    expect(editor.view.dom.textContent).not.toContain(REMOTE_IMAGE_BLOCKED_TEXT);
  });

  it('switching a node to a remote src swaps the img for the placeholder', () => {
    installCsp(false);
    const editor = makeEditor('![a](90-meta/assets/x.jpg)');
    editor.commands.setNodeSelection(0);
    editor.commands.updateAttributes('image', { src: 'https://example.com/c.png' });
    expect(editor.view.dom.querySelector('img')).toBeNull();
    expect(editor.view.dom.textContent).toContain(REMOTE_IMAGE_BLOCKED_TEXT);
  });
});
