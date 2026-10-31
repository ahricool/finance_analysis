import { expect, test, type Page } from '@playwright/test';

const smokePassword = process.env.FA_WEB_SMOKE_PASSWORD;

const smokeEmail = process.env.FA_WEB_SMOKE_EMAIL ?? 'whoreahri@gmail.com';

async function login(page: Page) {
  test.skip(!smokePassword, 'Set FA_WEB_SMOKE_PASSWORD to run authenticated smoke tests.');

  await page.goto('/login');
  await page.waitForLoadState('domcontentloaded');

  const dashboardLink = page.getByRole('link', { name: '市场动态' });

  const isAlreadyAuthenticated =
    page.url().endsWith('/dashboard') ||
    (await dashboardLink.isVisible({ timeout: 2_000 }).catch(() => false));

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
      '研究': ['量化研究', 'ETF 动量轮动', '趋势跟踪'],
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

  test('analysis page and nav entry are removed after login', async ({ page }) => {
    await login(page);
    await page.goto('/analysis');

    await expect(page.getByRole('heading', { name: '页面未找到' })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('link', { name: '分析' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: '时间线' })).toBeVisible();
    await expect(page.getByRole('button', { name: '研究' })).toBeVisible();
    await expect(page.getByRole('button', { name: '任务中心' })).toBeVisible();
    await expect(page.getByRole('link', { name: '问股' })).toHaveCount(0);
    await expect(page.getByText('历史分析', { exact: true })).toHaveCount(0);
  });

  test('legacy chat URL redirects to dashboard', async ({ page }) => {
    await mockAuthenticatedSession(page);
    await page.goto('/chat');
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole('link', { name: '问股' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: '分析' })).toHaveCount(0);
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
    await page.getByTestId('global-market-switch').click();
    for (const label of ['全部', '财报', '宏观']) {
      await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible();
    }
    await expect(page.getByRole('button', { name: '笔记', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '财经事件', exact: true })).toHaveCount(0);
    const filterButton = await page.getByRole('button', { name: '财报', exact: true }).boundingBox();
    const datePicker = await page.getByTestId('investment-timeline').getByRole('button', { name: /\d{4}年/ }).boundingBox();
    expect(filterButton?.height).toBe(datePicker?.height);
  });

  test('settings and theme navigation entries are removed after login', async ({ page }) => {
    await login(page);

    await expect(page.getByRole('link', { name: '设置' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '切换主题' })).toHaveCount(0);
  });
});

test('investment feed shows earnings and macro details across viewports', async ({ page }) => {
  await mockAuthenticatedSession(page);
  const base = { market: 'US', related_symbols: ['NVDA', 'AMD'], symbol: null, calendar_type: null, actionability: 'watch', impact: null, impact_score: null, importance_score: null, event_type: null };
  const items = [
    { ...base, id: 'finance_event:6', source_type: 'finance_event', source_id: 6, calendar_type: 'earnings', symbol: 'NVDA', related_symbols: ['NVDA'], event_time: '2026-11-18T21:00:00Z', category: 'event', title: 'NVDA 财报', summary: '', importance: 'high', importance_score: 9, detail_type: 'event', detail_payload: { counter_name: 'NVIDIA', reporting_period: 'Q3', market_session: 'amc', currency: 'USD', eps_estimate: 1.32, all_day: true, source_providers: ['longbridge', 'yfinance'] } },
    { ...base, id: 'finance_event:2', source_type: 'finance_event', source_id: 2, calendar_type: 'macro', related_symbols: [], event_time: '2026-09-06T00:30:00Z', category: 'event', title: '美国消费者价格指数（CPI）', summary: '关注核心通胀与利率预期的变化，以及对成长股估值的影响。', importance: 'critical', detail_type: 'event', detail_payload: { content: '美国消费者价格指数发布。' } },
  ];
  await page.route('**/api/v1/timeline?**', route => route.fulfill({ json: { items, total: items.length, next_cursor: null, has_more: false, limit: 20 } }));
  await page.clock.setFixedTime(new Date('2026-09-09T08:00:00Z'));
  items[0]!.event_time = '2026-09-06T02:00:00Z';
  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto('/timeline');
    await expect(page.getByTestId('timeline-item')).toHaveCount(2);
    await expect(page.getByTestId('timeline-item').first()).toContainText('EPS 预期 $1.32');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const columns = page.getByTestId('timeline-columns').first();
    const columnCount = '2';
    await expect(columns).toHaveCSS('column-count', columnCount);
    const wrappers = columns.locator(':scope > div');
    for (const wrapper of await wrappers.all()) {
      await expect(wrapper).toHaveCSS('break-inside', 'avoid');
      expect(await wrapper.evaluate(el => el.getClientRects().length)).toBe(1);
    }
    expect(await page.getByTestId('timeline-item').evaluateAll(cards => cards.map(card => card.getAttribute('aria-label'))))
      .toEqual(items.map(item => `查看${item.title}`));
    await page.screenshot({ path: `test-results/timeline-${width}.png`, fullPage: true });
  }
  await page.getByRole('button', { name: '查看美国消费者价格指数（CPI）' }).click();
  await expect(page.getByRole('dialog')).toContainText('美国消费者价格指数发布。');
});
