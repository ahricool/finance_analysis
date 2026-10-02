/**
 * Snapshot-backed UI audit screenshots + overflow / clip / overlap probes.
 * Requires FA production snapshot at FA_SNAPSHOT_DIR (default /opt/cursor/fa-snapshot).
 * Do NOT commit snapshot JSON — it stays outside the repo.
 *
 * Usage:
 *   WEB_ORIGIN=http://localhost:5173 node scripts/ui_audit_snapshot_screenshots.mjs after
 */
import { chromium } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { fileURLToPath, pathToFileURL } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const mockModuleUrl = pathToFileURL(
  path.resolve(__dirname, '../e2e/fixtures/installFaSnapshotMocks.mjs'),
).href;
const { installFaSnapshotMocks } = await import(mockModuleUrl);

const phase = process.argv[2] === 'after' ? 'after' : 'before';
const outRoot = `/opt/cursor/artifacts/ui-audit-snapshot/${phase}`;
const reportPath = path.join(outRoot, 'audit-report.json');
const WEB_ORIGIN = process.env.WEB_ORIGIN || 'http://localhost:5173';
const widths = [1440, 1280, 1024, 768, 390];
const height = 900;
const findings = [];

const routes = [
  { id: 'dashboard', path: '/dashboard' },
  { id: 'watch-list', path: '/market/watch-list' },
  { id: 'holdings', path: '/market/holdings' },
  { id: 'etf-rotation', path: '/research/etf-rotation' },
  { id: 'trend-following', path: '/research/trend-following' },
  { id: 'industry-strength', path: '/research/industry-strength' },
  { id: 'dragon-tiger-flow', path: '/research/dragon-tiger-flow' },
  { id: 'confluence', path: '/research/confluence' },
  { id: 'signal-center', path: '/research/signal-center' },
  { id: 'intraday-confirmation', path: '/research/intraday-confirmation' },
  { id: 'market-sentiment', path: '/research/market-sentiment' },
  { id: 'macro', path: '/research/macro' },
  { id: 'quant', path: '/research/quant' },
  { id: 'crypto-btc', path: '/crypto/btc' },
  { id: 'tasks', path: '/tasks/scheduled' },
  { id: 'notifications', path: '/notifications' },
  { id: 'timeline', path: '/timeline' },
];

async function stubBinance(page) {
  await page.route('https://data-api.binance.vision/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        Array.from({ length: 120 }, (_, i) => [
          1_725_000_000_000 + i * 900_000,
          '110000',
          '111000',
          '109000',
          String(110000 + i * 10),
          '12.5',
          1_725_000_000_000 + i * 900_000 + 899_999,
          '1.2',
          100,
          '0',
          '0',
          '0',
        ]),
      ),
    });
  });
  await page.routeWebSocket('wss://data-stream.binance.vision/ws', (ws) => {
    ws.close();
  });
}

async function auditPage(page, width, routeId) {
  return page.evaluate(({ width: w, routeId: id }) => {
    const issues = [];
    const doc = document.documentElement;
    if (doc.scrollWidth > window.innerWidth + 2) {
      issues.push({
        kind: 'page-overflow',
        detail: `scrollWidth=${doc.scrollWidth} clientWidth=${window.innerWidth}`,
      });
    }

    const candidates = Array.from(document.querySelectorAll(
      'h1,h2,h3,h4,[data-slot="bilingual-label"],[data-slot="bilingual-enum"],[data-slot="card-title"],[data-slot="badge"],th,td,button,a,strong,p',
    )).slice(0, 400);

    for (const el of candidates) {
      const style = getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
      const rect = el.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) continue;

      // Horizontal page clip (element extends past viewport without intentional scroll container)
      if (rect.right > window.innerWidth + 1 && rect.left < window.innerWidth) {
        let scrollParent = el.parentElement;
        let intentional = false;
        while (scrollParent && scrollParent !== document.body) {
          const overflowX = getComputedStyle(scrollParent).overflowX;
          if ((overflowX === 'auto' || overflowX === 'scroll') && scrollParent.scrollWidth > scrollParent.clientWidth + 2) {
            intentional = true;
            break;
          }
          scrollParent = scrollParent.parentElement;
        }
        if (!intentional) {
          issues.push({
            kind: 'element-clip',
            tag: el.tagName.toLowerCase(),
            text: (el.textContent || '').trim().slice(0, 80),
            detail: `right=${Math.round(rect.right)} vw=${window.innerWidth}`,
          });
        }
      }

      // Text overflow: content wider than box with overflow hidden / no wrap
      if (el.scrollWidth > el.clientWidth + 2) {
        const overflow = style.overflowX;
        if (overflow === 'hidden' || overflow === 'clip' || style.textOverflow === 'ellipsis') {
          // ellipsis truncation is intentional; only flag when no title/tooltip and looks like cut mid-word huge type
          const hasTip = Boolean(el.getAttribute('title') || el.closest('[title]'));
          if (!hasTip && (parseFloat(style.fontSize) >= 28 || el.matches('[data-slot="bilingual-enum"]'))) {
            issues.push({
              kind: 'text-clip',
              tag: el.tagName.toLowerCase(),
              text: (el.textContent || '').trim().slice(0, 80),
              detail: `scrollWidth=${el.scrollWidth} clientWidth=${el.clientWidth} font=${style.fontSize}`,
            });
          }
        }
      }

      // Vertical clip: content taller than box with overflow hidden/clip
      if (el.scrollHeight > el.clientHeight + 2) {
        const overflowY = style.overflowY;
        if (overflowY === 'hidden' || overflowY === 'clip') {
          // Intentional scroll areas are auto/scroll; fixed-height chips/badges are the target
          issues.push({
            kind: 'vertical-clip',
            tag: el.tagName.toLowerCase(),
            text: (el.textContent || '').trim().slice(0, 80),
            detail: `scrollHeight=${el.scrollHeight} clientHeight=${el.clientHeight} overflowY=${overflowY}`,
          });
        }
      }
    }

    // Child box extends past non-visible overflow parent (e.g. Badge h-5 + stacked bilingual)
    const clipParents = Array.from(document.querySelectorAll(
      '[data-slot="badge"], .overflow-hidden, [class*="overflow-hidden"]',
    )).slice(0, 200);
    for (const parent of clipParents) {
      const pStyle = getComputedStyle(parent);
      const oy = pStyle.overflowY;
      const ox = pStyle.overflowX;
      if (oy === 'visible' && ox === 'visible') continue;
      const pr = parent.getBoundingClientRect();
      if (pr.width < 2 || pr.height < 2) continue;
      for (const child of Array.from(parent.children).slice(0, 12)) {
        const cr = child.getBoundingClientRect();
        if (cr.width < 1 || cr.height < 1) continue;
        const pastBottom = cr.bottom > pr.bottom + 1.5;
        const pastTop = cr.top < pr.top - 1.5;
        const pastRight = cr.right > pr.right + 1.5;
        const pastLeft = cr.left < pr.left - 1.5;
        if ((pastBottom || pastTop) && (oy === 'hidden' || oy === 'clip')) {
          issues.push({
            kind: 'parent-clip-y',
            tag: parent.tagName.toLowerCase(),
            text: (child.textContent || parent.textContent || '').trim().slice(0, 80),
            detail: `childBottom=${Math.round(cr.bottom)} parentBottom=${Math.round(pr.bottom)}`,
          });
        }
        if ((pastRight || pastLeft) && (ox === 'hidden' || ox === 'clip')) {
          issues.push({
            kind: 'parent-clip-x',
            tag: parent.tagName.toLowerCase(),
            text: (child.textContent || parent.textContent || '').trim().slice(0, 80),
            detail: `childRight=${Math.round(cr.right)} parentRight=${Math.round(pr.right)}`,
          });
        }
      }
    }

    // Simple overlap among metric cards / regime headings in first viewport
    const blocks = Array.from(document.querySelectorAll(
      '[data-slot="bilingual-enum"], [data-testid="market-dashboard"] h2, [data-testid="trend-summary"] [data-slot="card"]',
    )).slice(0, 40);
    const boxes = blocks.map(el => {
      const r = el.getBoundingClientRect();
      return { el, r, text: (el.textContent || '').trim().slice(0, 60) };
    }).filter(b => b.r.width > 8 && b.r.height > 8 && b.r.top < window.innerHeight && b.r.bottom > 0);

    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i].r;
        const b = boxes[j].r;
        const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (overlapX > 8 && overlapY > 8) {
          // Ignore nested containment
          const aContainsB = a.left <= b.left && a.right >= b.right && a.top <= b.top && a.bottom >= b.bottom;
          const bContainsA = b.left <= a.left && b.right >= a.right && b.top <= a.top && b.bottom >= a.bottom;
          if (!aContainsB && !bContainsA) {
            issues.push({
              kind: 'overlap',
              text: `${boxes[i].text} ∩ ${boxes[j].text}`,
              detail: `overlap=${Math.round(overlapX)}x${Math.round(overlapY)}`,
            });
          }
        }
      }
    }

    return { width: w, routeId: id, issues: issues.slice(0, 30) };
  }, { width, routeId });
}

async function shot(page, dir, name, width) {
  fs.mkdirSync(dir, { recursive: true });
  await page.screenshot({ path: path.join(dir, `${name}.png`), fullPage: false });
  const result = await auditPage(page, width, name);
  if (result.issues.length) {
    findings.push(result);
    for (const issue of result.issues.slice(0, 8)) {
      console.warn(`FINDING ${phase} ${width}/${name}: ${issue.kind} ${issue.detail || ''} ${issue.text || ''}`);
    }
  } else {
    console.log(`ok ${phase} ${width}/${name}`);
  }
}

async function capture() {
  fs.mkdirSync(outRoot, { recursive: true });
  const browser = await chromium.launch({ headless: true });

  for (const width of widths) {
    const context = await browser.newContext({ viewport: { width, height } });
    const page = await context.newPage();
    await page.addInitScript(() => {
      localStorage.setItem('theme', 'light');
      localStorage.setItem('display_timezone', 'Asia/Shanghai');
    });
    await installFaSnapshotMocks(page, { useSyntheticHoldings: true });
    await stubBinance(page);

    await page.goto(`${WEB_ORIGIN}/dashboard`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);

    const dir = path.join(outRoot, String(width));

    // Hamburger below lg (1024)
    if (width < 1024) {
      const trigger = page.getByTestId('mobile-nav-trigger');
      if (await trigger.isVisible()) {
        await trigger.click();
        await page.waitForTimeout(450);
        await shot(page, dir, 'mobile-nav-open', width);
        await page.keyboard.press('Escape');
        await page.waitForTimeout(250);
      } else {
        findings.push({
          width,
          routeId: 'mobile-nav-trigger',
          issues: [{ kind: 'missing-nav', detail: 'mobile-nav-trigger not visible below lg' }],
        });
        console.warn(`FINDING ${phase} ${width}: mobile-nav-trigger not visible`);
      }
    }

    for (const route of routes) {
      await page.goto(`${WEB_ORIGIN}${route.path}`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1400);
      await shot(page, dir, route.id, width);
    }

    // Empty holdings (prod snapshot) vs synthetic — only once at 390
    if (width === 390) {
      await context.close();
      const emptyCtx = await browser.newContext({ viewport: { width, height } });
      const emptyPage = await emptyCtx.newPage();
      await emptyPage.addInitScript(() => {
        localStorage.setItem('theme', 'light');
        localStorage.setItem('display_timezone', 'Asia/Shanghai');
      });
      await installFaSnapshotMocks(emptyPage, { useSyntheticHoldings: false });
      await stubBinance(emptyPage);
      await emptyPage.goto(`${WEB_ORIGIN}/market/holdings`, { waitUntil: 'domcontentloaded' });
      await emptyPage.waitForTimeout(1200);
      await shot(emptyPage, dir, 'holdings-empty-prod', width);
      await emptyCtx.close();
      continue;
    }

    await context.close();
  }

  // Failure UX probes at 768
  {
    const width = 768;
    const dir = path.join(outRoot, String(width));
    const context = await browser.newContext({ viewport: { width, height } });
    const page = await context.newPage();
    await page.addInitScript(() => {
      localStorage.setItem('theme', 'light');
      localStorage.setItem('display_timezone', 'Asia/Shanghai');
    });
    await installFaSnapshotMocks(page, { useSyntheticHoldings: true });
    await stubBinance(page);

    await page.goto(`${WEB_ORIGIN}/research/etf-rotation`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);
    const previewToggle = page.getByTestId('research-mode-preview');
    if (await previewToggle.count()) {
      await previewToggle.click().catch(() => {});
      await page.waitForTimeout(1000);
      await shot(page, dir, 'etf-cn-preview-404-empty', width);
    }

    await page.goto(`${WEB_ORIGIN}/research/trend-following`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1800);
    await page.evaluate(() => {
      const el = document.querySelector('[data-testid="trend-event-study"], section');
      el?.scrollIntoView({ block: 'start' });
    });
    await page.waitForTimeout(800);
    await shot(page, dir, 'trend-event-study-cn', width);

    await context.close();
  }

  fs.writeFileSync(reportPath, JSON.stringify({ phase, findings, count: findings.length }, null, 2));
  await browser.close();
  console.log(`done ${phase} -> ${outRoot} findings=${findings.length}`);
}

await capture();
