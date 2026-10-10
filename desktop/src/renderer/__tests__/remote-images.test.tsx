import { afterEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { rendererCsp } from '../../shared/renderer-csp';
import {
  REMOTE_IMAGE_BLOCKED_TEXT,
  isRemoteImageSrc,
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

describe('isRemoteImageSrc', () => {
  it('is true for http and https URLs only', () => {
    expect(isRemoteImageSrc('https://example.com/a.png')).toBe(true);
    expect(isRemoteImageSrc('HTTP://example.com/a.png')).toBe(true);
    expect(isRemoteImageSrc('//example.com/a.png')).toBe(true);
    expect(isRemoteImageSrc('gbasset://asset/x.jpg')).toBe(false);
    expect(isRemoteImageSrc('data:image/png;base64,AAAA')).toBe(false);
    expect(isRemoteImageSrc('90-meta/assets/x.jpg')).toBe(false);
    expect(isRemoteImageSrc('')).toBe(false);
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
