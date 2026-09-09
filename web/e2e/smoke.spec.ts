import { expect, test, type Page } from '@playwright/test';

const smokePassword = process.env.FA_WEB_SMOKE_PASSWORD;

const smokeEmail = process.env.FA_WEB_SMOKE_EMAIL ?? 'whoreahri@gmail.com';

async function login(page: Page) {
  test.skip(!smokePassword, 'Set FA_WEB_SMOKE_PASSWORD to run authenticated smoke tests.');

  await page.goto('/login');
  await page.waitForLoadState('domcontentloaded');

  const analysisLink = page.getByRole('link', { name: '分析' });

  const isAlreadyAuthenticated =
    page.url().endsWith('/dashboard') ||
    (await analysisLink.isVisible({ timeout: 2_000 }).catch(() => false));

  if (isAlreadyAuthenticated) {
    await page.waitForLoadState('domcontentloaded');
    return;
  }

  const emailInput = page.getByTestId('login-email');
  await expect(emailInput).toBeVisible({ timeout: 10_000 });
  await emailInput.fill(smokeEmail);

  await Promise.all([
    page.waitForResponse(
      (response) => response.url().includes('/api/v1/auth/lookup') && response.status() === 200,
      { timeout: 15_000 },
    ),
    page.getByTestId('login-submit').click(),
  ]);

  const passwordInput = page.getByTestId('login-password');
  await expect(passwordInput).toBeVisible({ timeout: 10_000 });
  await passwordInput.fill(smokePassword!);

  await Promise.all([
    page.waitForResponse(
      (response) => response.url().includes('/api/v1/auth/login') && response.status() === 200,
      { timeout: 15_000 },
    ),
    page.getByTestId('login-submit').click(),
  ]);

  await page.waitForURL('**/dashboard', { timeout: 15_000 });
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(1000);
}

async function mockAuthenticatedSession(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    let body: object = {};

    if (url.pathname === '/api/v1/auth/status') {
      body = {
        loggedIn: true,
        user: {
          uid: 1,
          username: 'Desktop Tester',
          email: 'desktop@example.com',
          avatarUrl: null,
          role: 'user',
          extra: { gender: 'unknown' },
        },
      };
    } else if (url.pathname === '/api/v1/timeline/summary') {
      body = [];
    } else if (url.pathname === '/api/v1/timeline') {
      body = {
        date: url.searchParams.get('date'),
        items: [],
        total: 0,
        next_cursor: null,
        has_more: false,
        limit: 20,
      };
    } else if (url.pathname === '/api/v1/watch-list') {
      body = { items: [], total: 0 };
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });
}

test.describe('web smoke', () => {
  test('root keeps a stable vertical scrollbar gutter during route changes', async ({ page }) => {
    await mockAuthenticatedSession(page);
    await page.goto('/timeline');

    await expect(page.locator('html')).toHaveCSS('scrollbar-gutter', 'stable');
  });

  test('header dropdown menus do not shift the page while opening', async ({ page }) => {
    await mockAuthenticatedSession(page);
    await page.setViewportSize({ width: 1440, height: 800 });
    await page.goto('/timeline');

    const headerContent = page.getByTestId('shell-header-content');
    const initialBox = await headerContent.boundingBox();
    expect(initialBox).not.toBeNull();
    const dropdownItems: Record<string, string[]> = {
      '市场': ['自选股', '投资组合'],
      '研究': ['量化研究', 'ETF动量轮动', '趋势跟踪'],
    };

    for (const label of ['市场', '研究', '打开用户菜单']) {
      await page.getByRole('button', { name: label, exact: true }).click();
      const menu = page.getByRole('menu');
      await expect(menu).toBeVisible();
      for (const itemLabel of dropdownItems[label] ?? []) {
        await expect(menu.getByRole('menuitem', { name: itemLabel })).toBeVisible();
      }

      expect(await headerContent.boundingBox()).toEqual(initialBox);
      expect(
        await page.evaluate(() => ({
          overflow: document.body.style.overflow,
          paddingRight: document.body.style.paddingRight,
        })),
      ).toEqual({ overflow: '', paddingRight: '' });

      await page.keyboard.press('Escape');
      await expect(page.getByRole('menu')).toBeHidden();
    }
  });

  test('login page renders the email step', async ({ page }) => {
    await page.route('**/api/v1/auth/status', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ loggedIn: false, user: null }),
      }),
    );
    await page.goto('/login');
    await page.waitForLoadState('domcontentloaded');

    await expect(page.getByText('Finance Analysis')).toBeVisible();
    await expect(page.getByTestId('login-email')).toBeVisible();
    await expect(page.getByTestId('login-password')).toHaveCount(0);
    const submitButton = page.getByRole('button', { name: '继续' });
    await expect(submitButton).toBeVisible();

    const emailBox = await page.getByTestId('login-email').boundingBox();
    const submitBox = await submitButton.boundingBox();
    expect(emailBox).not.toBeNull();
    expect(submitBox).not.toBeNull();
    expect(submitBox!.y - (emailBox!.y + emailBox!.height)).toBeGreaterThanOrEqual(20);
  });

  test('login password visibility toggle works without controlled state', async ({ page }) => {
    await page.route('**/api/v1/auth/status', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ loggedIn: false, user: null }),
      }),
    );
    await page.route('**/api/v1/auth/lookup', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, needsPasswordSetup: false }),
      }),
    );
    await page.goto('/login');
    await page.getByTestId('login-email').fill('tester@example.com');
    await page.getByRole('button', { name: '继续' }).click();

    const password = page.getByLabel('登录密码');
    await expect(password).toHaveAttribute('type', 'password');
    await page.getByRole('button', { name: '显示内容' }).click();
    await expect(password).toHaveAttribute('type', 'text');
    await page.getByRole('button', { name: '隐藏内容' }).click();
    await expect(password).toHaveAttribute('type', 'password');
  });

  test('analysis page shows analysis entry and history panel after login', async ({ page }) => {
    await login(page);
    await page.goto('/analysis');

    const stockInput = page.getByPlaceholder('输入股票代码或名称，如 600519、贵州茅台、AAPL');
    await expect(stockInput).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('link', { name: '分析' })).toBeVisible();
    await expect(page.getByRole('link', { name: '时间线' })).toBeVisible();
    await expect(page.getByRole('button', { name: '研究' })).toBeVisible();
    await expect(page.getByRole('link', { name: '任务中心' })).toBeVisible();
    await expect(page.getByRole('link', { name: '问股' })).toHaveCount(0);
    await expect(page.getByText('历史分析', { exact: true })).toBeVisible();

    await stockInput.fill('600519');
    const analyzeButton = page.getByRole('button', { name: '分析', exact: true });
    await expect(analyzeButton).toBeVisible();
  });

  test('legacy chat URL redirects to analysis', async ({ page }) => {
    await mockAuthenticatedSession(page);
    await page.goto('/chat');
    await expect(page).toHaveURL(/\/analysis$/);
    await expect(page.getByTestId('analysis-workspace')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('link', { name: '问股' })).toHaveCount(0);
  });

  test('shell remains usable without horizontal overflow at all required breakpoints', async ({
    page,
  }) => {
    await mockAuthenticatedSession(page);
    const viewports = [{ width: 1280, height: 900 }, { width: 1440, height: 1000 }, { width: 1920, height: 1080 }];

    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await page.goto('/timeline');
      await expect(page.getByRole('heading', { name: '投资时间线' })).toBeVisible();
      await expect(page.getByTestId('desktop-main-nav')).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
    }
  });

  test('timeline filter rows use equal-height controls', async ({ page }) => {
    await mockAuthenticatedSession(page);
    await page.goto('/timeline');
    await page.getByRole('button', { name: '美股', exact: true }).click();
    for (const label of ['全部', '财报', '宏观', '新闻', '市场分析']) {
      await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible();
    }
    await expect(page.getByRole('button', { name: '笔记', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '财经事件', exact: true })).toHaveCount(0);
    const marketButton = await page.getByRole('button', { name: '美股', exact: true }).boundingBox();
    const datePicker = await page.getByTestId('investment-timeline').getByRole('button', { name: /\d{4}年/ }).boundingBox();
    expect(marketButton?.height).toBe(datePicker?.height);
  });

  test('settings and theme navigation entries are removed after login', async ({ page }) => {
    await login(page);

    await expect(page.getByRole('link', { name: '设置' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '切换主题' })).toHaveCount(0);
  });
});

test('investment feed shows individual items and report details across viewports', async ({ page }) => {
  await mockAuthenticatedSession(page);
  const base = { market: 'US', related_symbols: ['NVDA', 'AMD'], symbol: null, calendar_type: null, actionability: 'watch', impact: null, impact_score: null, importance_score: null, event_type: null };
  const items = [
    { ...base, id: 'finance_event:6', source_type: 'finance_event', source_id: 6, calendar_type: 'earnings', symbol: 'NVDA', related_symbols: ['NVDA'], event_time: '2026-11-18T21:00:00Z', category: 'event', title: 'NVDA 财报', summary: '', importance: 'high', importance_score: 9, detail_type: 'event', detail_payload: { counter_name: 'NVIDIA', reporting_period: 'Q3', market_session: 'amc', currency: 'USD', eps_estimate: 1.32, all_day: true, source_providers: ['longbridge', 'yfinance'] } },
    { ...base, id: 'report:1', source_type: 'report', source_id: 1, event_time: '2026-09-06T01:00:00Z', category: 'analysis', title: '美股盘前分析：关注科技股趋势与开盘风险', summary: '市场方向仍待成交确认。复核重点持仓，留意关键价位与开盘后的量能变化。', importance: 'high', actionability: 'consider', detail_type: 'report', detail_payload: { content: '# 美股盘前分析\n\n## 持仓风险\n\n等待趋势确认，避免开盘追高。' } },
    { ...base, id: 'finance_event:2', source_type: 'finance_event', source_id: 2, calendar_type: 'macro', related_symbols: [], event_time: '2026-09-06T00:30:00Z', category: 'event', title: '美国消费者价格指数（CPI）', summary: '关注核心通胀与利率预期的变化，以及对成长股估值的影响。', importance: 'critical', detail_type: 'event', detail_payload: { content: '美国消费者价格指数发布。' } },
    { ...base, id: 'news:3', source_type: 'news', source_id: 3, event_time: '2026-09-05T23:45:00Z', category: 'news', title: 'NVIDIA 数据中心需求增长，供应链展望上调', summary: '新增订单反映需求韧性，后续关注产能交付与客户资本开支。', importance: 'critical', importance_score: 9, impact: 'bullish', impact_score: 3, detail_type: 'news', detail_payload: { source: '示例新闻', url: 'https://example.com/news', published_at: '2026-09-05T23:45:00Z', importance_reason: '需求变化影响盈利预期', watch_points: ['交付进度'], risk_notes: ['估值风险'] } },
    { ...base, id: 'report:4', source_type: 'report', source_id: 4, event_time: '2026-09-05T10:00:00Z', category: 'analysis', title: '美股收盘复盘：市场分歧与下一交易日观察', summary: '指数走势分化，防御板块相对强势。继续观察科技股能否重获资金支持。', importance: 'high', detail_type: 'report', detail_payload: { content: '# 收盘复盘' } },
    { ...base, id: 'report:5', source_type: 'report', source_id: 5, market: 'CN', related_symbols: ['600519.SH'], event_time: '2026-09-05T06:30:00Z', category: 'analysis', title: 'A股收盘前复核：尾盘风险与持仓调整', summary: '成交趋弱，优先复核持仓风险，等待板块持续性验证。', importance: 'high', actionability: 'consider', detail_type: 'report', detail_payload: { content: '# A股收盘前复核' } },
  ];
  await page.route('**/api/v1/timeline?**', route => route.fulfill({ json: { items, total: items.length, next_cursor: null, has_more: false, limit: 20 } }));
  await page.clock.setFixedTime(new Date('2026-09-09T08:00:00Z'));
  items[0]!.event_time = '2026-09-06T02:00:00Z';
  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto('/timeline');
    await expect(page.getByTestId('timeline-item')).toHaveCount(6);
    await expect(page.getByTestId('timeline-item').first()).toContainText('EPS 预期 $1.32');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const columns = page.getByTestId('timeline-columns').first();
    await expect(columns).toHaveCSS('column-count', '2');
    const wrappers = columns.locator(':scope > div');
    for (const wrapper of await wrappers.all()) {
      await expect(wrapper).toHaveCSS('break-inside', 'avoid');
      expect(await wrapper.evaluate(el => el.getClientRects().length)).toBe(1);
    }
    expect(await page.getByTestId('timeline-item').evaluateAll(cards => cards.map(card => card.getAttribute('aria-label'))))
      .toEqual(items.map(item => `查看${item.title}`));
    const boxes = await page.getByTestId('timeline-item').evaluateAll(cards => cards.slice(0, 4).map(card => ({ x: card.getBoundingClientRect().x, height: card.getBoundingClientRect().height })));
    expect(new Set(boxes.map(box => Math.round(box.x))).size).toBe(2);
    expect(new Set(boxes.map(box => Math.round(box.height))).size).toBeGreaterThan(1);
    await page.screenshot({ path: `test-results/timeline-${width}.png`, fullPage: true });
  }
  await page.getByRole('button', { name: '查看美股盘前分析：关注科技股趋势与开盘风险' }).click();
  await expect(page.getByRole('heading', { name: '持仓风险' })).toBeVisible();
});
