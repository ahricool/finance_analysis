/**
 * Playwright mocks backed by an offline FA production API snapshot.
 *
 * Snapshot stays OUTSIDE the git repo (default: FA_SNAPSHOT_DIR or /opt/cursor/fa-snapshot).
 * Auth responses were privacy-scrubbed from the snapshot — we inject a synthetic admin.
 * Holdings are empty in production — optional synthetic holdings override for layout review.
 */
import fs from 'fs';
import path from 'path';

const SNAPSHOT_DIR = process.env.FA_SNAPSHOT_DIR || '/opt/cursor/fa-snapshot';

function authOk() {
  return {
    loggedIn: true,
    user: {
      uid: 1,
      username: 'UI Auditor',
      email: 'auditor@example.com',
      avatarUrl: null,
      role: 'admin',
      extra: { gender: 'unknown' },
    },
  };
}

/** Dense synthetic holdings for layout review (prod snapshot cash=0 / no positions). */
function syntheticHoldingsSummary(market) {
  const isCn = market === 'CN';
  return {
    market,
    accounts: [{
      id: isCn ? 1 : 2,
      name: isCn ? 'A股账户' : '美股账户',
      market,
      cash: isCn ? '1234567.89000000' : '98765.43000000',
      currency: isCn ? 'CNY' : 'USD',
    }],
    cash: isCn ? '1234567.89000000' : '98765.43000000',
    market_value: isCn ? '87654321.00' : '9753086.43',
    total_asset: isCn ? '88888888.89000000' : '9851852.21000000',
    gross_exposure: '0.98650000',
    positions: Array.from({ length: isCn ? 12 : 8 }, (_, i) => ({
      id: 100 + i,
      account_id: isCn ? 1 : 2,
      market,
      symbol: i === 0
        ? (isCn ? '600519.SH' : 'NVDA.US')
        : `${isCn ? 600100 + i : 100 + i}.${isCn ? 'SH' : 'US'}`,
      name: i === 0
        ? (isCn ? '贵州茅台酒股份有限公司特别长期观察标的' : 'NVIDIA Corporation Ultra Long Name For Truncation')
        : `合成持仓${i}超长名称`,
      asset_type: i % 5 === 0 ? 'ETF' : 'STOCK',
      quantity: String(1000 + i * 37),
      average_cost: String(isCn ? 1688.5 - i * 10 : 120.5 + i),
      current_price: String(isCn ? 1750 + i : 140.2 + i),
      market_value: String(1_200_000 + i * 88_000),
      weight: String(0.12 - i * 0.003),
      unrealized_pnl: String(i % 2 === 0 ? 123456.78 : -98765.43),
      trade_engine_enabled: i % 4 !== 0,
      lots: [],
    })),
  };
}

function queryKey(query) {
  return Object.keys(query)
    .sort()
    .map((k) => `${k}=${query[k]}`)
    .join('&');
}

function loadIndex(dir) {
  const indexPath = path.join(dir, 'index.json');
  if (!fs.existsSync(indexPath)) {
    throw new Error(`FA snapshot index missing: ${indexPath}. Set FA_SNAPSHOT_DIR.`);
  }
  const entries = JSON.parse(fs.readFileSync(indexPath, 'utf8'));
  /** @type {Map<string, { status: number|null, file: string|null, body?: string }>} */
  const byExact = new Map();
  /** @type {Map<string, Array<{ query: Record<string,string>, status: number|null, file: string|null }>>} */
  const byPath = new Map();

  for (const entry of entries) {
    if (entry.method && entry.method !== 'GET') continue;
    const q = entry.query || {};
    const exact = `${entry.path}?${queryKey(q)}`;
    byExact.set(exact, { status: entry.status ?? null, file: entry.file ?? null });
    if (!byPath.has(entry.path)) byPath.set(entry.path, []);
    byPath.get(entry.path).push({ query: q, status: entry.status ?? null, file: entry.file ?? null });
  }
  return { byExact, byPath, dir };
}

function readBody(dir, file) {
  if (!file) return null;
  const full = path.join(dir, file);
  if (!fs.existsSync(full)) return null;
  return fs.readFileSync(full, 'utf8');
}

function pickBest(pathOnly, searchParams, byPath) {
  const candidates = byPath.get(pathOnly);
  if (!candidates?.length) return null;
  const incoming = {};
  for (const [k, v] of searchParams.entries()) incoming[k] = v;

  let best = null;
  let bestScore = -1;
  for (const c of candidates) {
    const keys = Object.keys(c.query);
    let score = 0;
    let mismatch = false;
    for (const k of keys) {
      if (!(k in incoming)) {
        // allow missing optional query on request if snapshot had a default-ish capture
        score -= 1;
        continue;
      }
      if (String(incoming[k]) !== String(c.query[k])) {
        mismatch = true;
        break;
      }
      score += 2;
    }
    // prefer fewer unspecified snapshot params when request has extras
    score -= Math.max(0, Object.keys(incoming).length - keys.length) * 0.1;
    if (!mismatch && score > bestScore) {
      bestScore = score;
      best = c;
    }
  }
  // fallback: empty-query capture for this path
  if (!best) {
    best = candidates.find((c) => Object.keys(c.query).length === 0) || candidates[0];
  }
  return best;
}

/**
 * @param {import('@playwright/test').Page} page
 * @param {{ useSyntheticHoldings?: boolean }} [options]
 */
export async function installFaSnapshotMocks(page, options = {}) {
  const useSyntheticHoldings = options.useSyntheticHoldings !== false;
  const catalog = loadIndex(SNAPSHOT_DIR);

  await page.route('**/api/v1/**', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const apiPath = url.pathname.replace(/\/$/, '') || url.pathname;
    const method = req.method();

    // Synthetic auth (privacy-removed in snapshot)
    if (apiPath === '/api/v1/auth/status' || apiPath === '/api/v1/auth/profile') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(authOk()) });
      return;
    }
    if (apiPath.startsWith('/api/v1/auth/')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
      return;
    }

    // Synthetic holdings overlay for dense layout review
    if (useSyntheticHoldings && apiPath === '/api/v1/holdings/summary') {
      const market = url.searchParams.get('market') || 'CN';
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(syntheticHoldingsSummary(market)),
      });
      return;
    }
    if (useSyntheticHoldings && apiPath === '/api/v1/holdings/positions') {
      const summary = syntheticHoldingsSummary('CN');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: summary.positions }),
      });
      return;
    }

    if (method !== 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, task_id: 'audit-task' }) });
      return;
    }

    const exactKey = `${apiPath}?${queryKey(Object.fromEntries(url.searchParams.entries()))}`;
    let hit = catalog.byExact.get(exactKey);
    if (!hit) {
      const best = pickBest(apiPath, url.searchParams, catalog.byPath);
      if (best) hit = { status: best.status, file: best.file };
    }

    // Timed-out capture (no file): surface as gateway timeout so UI can show failure, not empty.
    if (hit && (hit.status == null || hit.file == null) && apiPath.includes('event-study') && !apiPath.includes('/summary') && !apiPath.includes('/events')) {
      await route.fulfill({
        status: 504,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'snapshot capture timed out (production event-study CN)' }),
      });
      return;
    }

    if (!hit) {
      // Prefer empty successful shapes over hard 404 for unmatched GETs during audits.
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
      return;
    }

    const status = typeof hit.status === 'number' ? hit.status : 500;
    const body = readBody(catalog.dir, hit.file);
    if (body == null) {
      await route.fulfill({
        status: status >= 400 ? status : 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'snapshot body missing' }),
      });
      return;
    }
    await route.fulfill({ status, contentType: 'application/json', body });
  });
}

export { SNAPSHOT_DIR, syntheticHoldingsSummary };
