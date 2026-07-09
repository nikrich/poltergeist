// poltergeist promo site — minimal interactivity
// sticky nav, faq accordion, live "latest release" lookup that rewrites
// every download CTA to point straight at the visitor's platform installer.

(() => {
  const nav = document.getElementById('nav');
  const onScroll = () => {
    nav.classList.toggle('nav--scrolled', window.scrollY > 8);
  };
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });

  document.querySelectorAll('.faq__item').forEach(item => {
    const btn = item.querySelector('.faq__btn');
    btn.addEventListener('click', () => {
      const wasOpen = item.classList.contains('open');
      document.querySelectorAll('.faq__item.open').forEach(o => {
        o.classList.remove('open');
        o.querySelector('.faq__btn').setAttribute('aria-expanded', 'false');
      });
      if (!wasOpen) {
        item.classList.add('open');
        btn.setAttribute('aria-expanded', 'true');
      }
    });
  });

  // --- platform-aware download CTAs -----------------------------------------
  // The newest tag sometimes has no binaries yet (release-please cuts the
  // tag, then the platform build jobs upload installers minutes apart). So we
  // walk the release list and pick the first one that actually has an
  // installer for the visitor's OS. Everything keeps falling back to
  // /releases/latest if anything here goes sideways (offline, rate-limited,
  // blocked, etc.).
  const RELEASES_URL = 'https://api.github.com/repos/nikrich/poltergeist/releases?per_page=10';
  const FALLBACK_HREF = 'https://github.com/nikrich/poltergeist/releases/latest';

  const OS = (() => {
    const p = `${navigator.platform} ${navigator.userAgent}`;
    if (/mac/i.test(p)) return 'mac';
    if (/win/i.test(p)) return 'windows';
    return 'linux';
  })();

  // Matchers in preference order per OS (e.g. the NSIS installer beats the
  // bare win zip, the AppImage beats the deb).
  const ASSET_MATCHERS = {
    mac: [/\.dmg$/i],
    windows: [/\.exe$/i, /-win\.zip$/i],
    linux: [/\.appimage$/i, /\.deb$/i],
  };

  document.querySelectorAll('[data-dl-label]').forEach(el => {
    el.textContent = `download for ${OS}`;
  });

  const pickAsset = (releases) => {
    for (const r of releases) {
      if (r.draft || r.prerelease) continue;
      for (const matcher of ASSET_MATCHERS[OS]) {
        const hit = (r.assets || []).find(a => matcher.test(a.name));
        if (hit) return { tag: r.tag_name, url: hit.browser_download_url };
      }
    }
    return null;
  };

  const applyRelease = ({ tag, url }) => {
    document.querySelectorAll(`a[href="${FALLBACK_HREF}"]`).forEach(a => {
      a.href = url;
      // Direct download – open in same tab, drop noopener/target since we're
      // not punching out to a new tab anymore.
      a.removeAttribute('target');
      a.removeAttribute('rel');
    });

    const version = tag.startsWith('v') ? tag.slice(1) : tag;
    const hero = document.getElementById('hero-version');
    if (hero) hero.textContent = `v ${version} · desktop app`;
    const footer = document.getElementById('footer-version');
    if (footer) footer.textContent = `v ${version}`;
  };

  fetch(RELEASES_URL, { headers: { Accept: 'application/vnd.github+json' } })
    .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
    .then(releases => {
      const hit = pickAsset(releases);
      if (hit) applyRelease(hit);
      // If no release has an installer for this OS yet, leave the fallback
      // links alone.
    })
    .catch(() => {
      // Network/API failure – the hardcoded /releases/latest links still work.
    });
})();
