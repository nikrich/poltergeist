// Scripted Poltergeist showcase recorder.
//
// Launches the BUILT Electron app in demo mode (GHOSTBRAIN_DEMO=1 → synthetic
// fixtures, no Python sidecar, no real data), injects a smooth synthetic
// cursor, drives the hero flows from scenes.mjs, and records the window to a
// .webm. Post-process to MP4/GIF with postprocess.sh.
//
//   node scripts/demo/record.mjs
//
// Requires a prior `npm run build` (reads out/main/index.js).

import { _electron as electron } from 'playwright';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import { mkdirSync, existsSync, copyFileSync, readdirSync, statSync } from 'node:fs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const desktopDir = resolve(__dirname, '../..');
const repoRoot = resolve(desktopDir, '..');
const mainEntry = join(desktopDir, 'out/main/index.js');

const WIDTH = 1280;
const HEIGHT = 800;
const mediaDir = join(repoRoot, 'media');
const rawDir = join(mediaDir, '.raw');

// Visible synthetic cursor + click pulse. Injected once after load; lives on
// document.body so React re-renders (which only own #root) never remove it.
const CURSOR_SCRIPT = `(() => {
  if (window.__demo) return;
  const mk = () => {
    const c = document.createElement('div');
    c.id = '__demo_cursor';
    Object.assign(c.style, {
      position: 'fixed', top: '0', left: '0', width: '22px', height: '22px',
      zIndex: '2147483647', pointerEvents: 'none', willChange: 'transform',
      transform: 'translate(${WIDTH / 2}px, ${HEIGHT / 2}px)',
      filter: 'drop-shadow(0 1px 2px rgba(0,0,0,.45))',
    });
    c.innerHTML =
      '<svg width="22" height="22" viewBox="0 0 24 24" fill="none">' +
      '<path d="M5 3l14 7-6 1.6L9.5 18 5 3z" fill="#fff" stroke="#111" stroke-width="1.2" stroke-linejoin="round"/></svg>';
    document.body.appendChild(c);
    const ring = document.createElement('div');
    ring.id = '__demo_ring';
    Object.assign(ring.style, {
      position: 'fixed', top: '0', left: '0', width: '14px', height: '14px',
      borderRadius: '50%', border: '2px solid rgba(197,255,61,.95)',
      zIndex: '2147483646', pointerEvents: 'none', opacity: '0',
      transform: 'translate(-100px,-100px)',
    });
    document.body.appendChild(ring);
    return { c, ring };
  };
  let nodes = null;
  const ensure = () => { if (!nodes || !nodes.c.isConnected) nodes = mk(); return nodes; };
  let x = ${WIDTH / 2}, y = ${HEIGHT / 2};
  const ease = (k) => (k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2);
  window.__demo = {
    moveTo(tx, ty, dur = 650) {
      const { c } = ensure();
      return new Promise((res) => {
        const sx = x, sy = y, t0 = performance.now();
        const step = (t) => {
          const k = Math.min(1, (t - t0) / dur);
          const e = ease(k);
          x = sx + (tx - sx) * e; y = sy + (ty - sy) * e;
          c.style.transform = 'translate(' + x + 'px,' + y + 'px)';
          if (k < 1) requestAnimationFrame(step); else res();
        };
        requestAnimationFrame(step);
      });
    },
    pulse() {
      const { ring } = ensure();
      ring.style.transition = 'none';
      ring.style.transform = 'translate(' + (x - 5) + 'px,' + (y - 5) + 'px) scale(1)';
      ring.style.opacity = '1';
      requestAnimationFrame(() => {
        ring.style.transition = 'transform .45s ease-out, opacity .45s ease-out';
        ring.style.transform = 'translate(' + (x - 5) + 'px,' + (y - 5) + 'px) scale(2.6)';
        ring.style.opacity = '0';
      });
    },
  };
})();`;

async function main() {
  if (!existsSync(mainEntry)) {
    console.error(`[demo] missing build at ${mainEntry} — run \`npm run build\` first.`);
    process.exit(1);
  }
  mkdirSync(rawDir, { recursive: true });

  const app = await electron.launch({
    args: [mainEntry],
    env: { ...process.env, GHOSTBRAIN_DEMO: '1' },
    recordVideo: { dir: rawDir, size: { width: WIDTH, height: HEIGHT } },
  });

  const page = await app.firstWindow();
  await page.waitForLoadState('domcontentloaded');

  // Fix the window to a known content size so the recording is deterministic.
  await app.evaluate(async ({ BrowserWindow }, { w, h }) => {
    const win = BrowserWindow.getAllWindows()[0];
    if (win) {
      win.setContentSize(w, h);
      win.center();
      win.show();
      win.focus();
    }
  }, { w: WIDTH, h: HEIGHT });

  await page.addStyleTag({
    content: '#__demo_cursor,#__demo_ring{will-change:transform}',
  }).catch(() => {});
  await page.evaluate(CURSOR_SCRIPT);

  const beat = (ms) => page.waitForTimeout(ms);
  const log = (m) => console.log(`[demo] ${m}`);

  const cursorTo = async (locator) => {
    const el = locator.first();
    await el.waitFor({ state: 'visible', timeout: 15000 });
    await el.scrollIntoViewIfNeeded().catch(() => {});
    const box = await el.boundingBox();
    if (!box) throw new Error('no bounding box for target');
    const cx = Math.round(box.x + box.width / 2);
    const cy = Math.round(box.y + box.height / 2);
    await page.evaluate(([tx, ty]) => window.__demo.moveTo(tx, ty), [cx, cy]);
    return el;
  };

  const cursor = {
    move: cursorTo,
    async click(locator) {
      const el = await cursorTo(locator);
      await page.evaluate(() => window.__demo.pulse());
      await el.click();
    },
    async type(text) {
      await page.keyboard.type(text, { delay: 42 });
    },
  };

  const { runScenes } = await import('./scenes.mjs');
  try {
    await runScenes({ page, app, cursor, beat, log });
  } catch (err) {
    console.error('[demo] scene error:', err.message);
  }

  // Trailing frames so the loop doesn't cut abruptly.
  await beat(800);

  const video = page.video();
  const dest = join(mediaDir, 'poltergeist-demo.webm');

  // Bound the shutdown: even with a clean-quit app, never let close() hang the
  // pipeline. The video is flushed to rawDir on close regardless.
  await Promise.race([
    app.close(),
    new Promise((res) => setTimeout(res, 8000)),
  ]).catch(() => {});

  let src = null;
  if (video) src = await video.path().catch(() => null);
  if (!src || !existsSync(src)) src = newestWebm(rawDir);

  if (src && existsSync(src)) {
    copyFileSync(src, dest);
    console.log(`\n[demo] raw recording → ${dest}`);
    console.log('[demo] now run: npm run demo:post');
  } else {
    console.error('[demo] no video was recorded — check Playwright Electron recordVideo support.');
    process.exit(1);
  }
  process.exit(0);
}

function newestWebm(dir) {
  const files = readdirSync(dir)
    .filter((f) => f.endsWith('.webm'))
    .map((f) => join(dir, f));
  if (files.length === 0) return null;
  return files.sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs)[0];
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
