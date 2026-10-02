/**
 * Snapshot-backed UI audit screenshots.
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
const WEB_ORIGIN = process.env.WEB_ORIGIN || 'http://localhost:5173';
const widths = [1440, 1280, 768, 390];
const height = 900;

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

async function shot(page, dir, name) {
  fs.mkdirSync(dir, { recursive: true });
  await page.screenshot({ path: path.join(dir, `${name}.png`), fullPage: false });
  const overflow = await page.evaluate(() => ({
    doc: document.documentElement.scrollWidth,
    win: window.innerWidth,
  }));
  if (overflow.doc > overflow.win + 2) {
    console.warn(`OVERFLOW ${phase} ${name}: doc=${overflow.doc} win=${overflow.win}`);
  } else {
    console.log(`ok ${phase} ${name}`);
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

    if (width < 768) {
      const trigger = page.getByTestId('mobile-nav-trigger');
      if (await trigger.isVisible()) {
        await trigger.click();
        await page.waitForTimeout(450);
        await shot(page, dir, 'mobile-nav-open');
        await page.keyboard.press('Escape');
        await page.waitForTimeout(250);
      }
    }

    for (const route of routes) {
      await page.goto(`${WEB_ORIGIN}${route.path}`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1400);
      await shot(page, dir, route.id);
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
      await shot(emptyPage, dir, 'holdings-empty-prod');
      await emptyCtx.close();
      continue;
    }

    await context.close();
  }

  // Failure UX probes at 768: stock history 422/500, CN preview empty, trend event-study timeout
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

    // Watch list → open a row if possible; else navigate trend and scroll event study
    await page.goto(`${WEB_ORIGIN}/market/watch-list`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1200);

    // ETF CN official (preview 404 should not show as hard error when switching to preview)
    await page.goto(`${WEB_ORIGIN}/research/etf-rotation`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);
    const previewToggle = page.getByRole('radio', { name: /盘中预览|Preview/i }).first();
    if (await previewToggle.count()) {
      await previewToggle.click().catch(() => {});
      await page.waitForTimeout(1000);
      await shot(page, dir, 'etf-cn-preview-404-empty');
    }

    await page.goto(`${WEB_ORIGIN}/research/trend-following`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1800);
    await page.evaluate(() => {
      const el = document.querySelector('[data-testid="trend-event-study"], section');
      el?.scrollIntoView({ block: 'start' });
    });
    await page.waitForTimeout(800);
    await shot(page, dir, 'trend-event-study-cn');

    await context.close();
  }

  await browser.close();
  console.log(`done ${phase} -> ${outRoot}`);
}

await capture();
