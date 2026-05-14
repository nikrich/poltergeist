// poltergeist promo site — minimal interactivity
// sticky nav, faq accordion, live "latest release" lookup that rewrites
// every download CTA to point straight at the .dmg.

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

  // --- live release lookup -------------------------------------------------
  // The newest tag sometimes has no binaries yet (release-please cuts the
  // tag, then the mac build job uploads the .dmg minutes later). So we walk
  // the release list and pick the first one that actually has a .dmg
  // attached. Everything keeps falling back to /releases/latest if anything
  // here goes sideways (offline, rate-limited, blocked, etc.).
  const RELEASES_URL = 'https://api.github.com/repos/nikrich/ghost-brain/releases?per_page=10';
  const FALLBACK_HREF = 'https://github.com/nikrich/ghost-brain/releases/latest';

  const pickDmg = (releases) => {
    for (const r of releases) {
      if (r.draft || r.prerelease) continue;
      const dmg = (r.assets || []).find(a => a.name.toLowerCase().endsWith('.dmg'));
      if (dmg) return { tag: r.tag_name, url: dmg.browser_download_url };
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
      const hit = pickDmg(releases);
      if (hit) applyRelease(hit);
      // If no release has a .dmg yet, leave the fallback links alone.
    })
    .catch(() => {
      // Network/API failure – the hardcoded /releases/latest links still work.
    });
})();
