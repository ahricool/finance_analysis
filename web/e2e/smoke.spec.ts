import { expect, test, type Page } from '@playwright/test';

const smokePassword = process.env.FA_WEB_SMOKE_PASSWORD;

const smokeEmail = process.env.FA_WEB_SMOKE_EMAIL ?? 'whoreahri@gmail.com';

async function login(page: Page) {
  test.skip(!smokePassword, 'Set FA_WEB_SMOKE_PASSWORD to run authenticated smoke tests.');

  await page.goto('/login');
  await page.waitForLoadState('domcontentloaded');

  const analysisLink = page.getByRole('link', { name: '分析' });

  const isAlreadyAuthenticated =
    page.url().endsWith('/analysis') ||
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

  await page.waitForURL('**/analysis', { timeout: 15_000 });
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
          username: 'Mobile Tester',
          email: 'mobile@example.com',
          avatarUrl: null,
          role: 'user',
          extra: { gender: 'unknown' },
        },
      };
    } else if (url.pathname === '/api/v1/calendar/summary') {
      body = {
        start_date: url.searchParams.get('start_date'),
        end_date: url.searchParams.get('end_date'),
        items: [],
      };
    } else if (url.pathname === '/api/v1/calendar' || url.pathname === '/api/v1/calendar/events') {
      body = {
        date: url.searchParams.get('date'),
        items: [],
        total: 0,
        page: 1,
        limit: 20,
      };
    } else if (url.pathname === '/api/v1/watch-list') {
      body = { items: [], total: 0 };
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('web smoke', () => {
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
    await expect(page.getByRole('button', { name: '继续' })).toBeVisible();
  });

  test('analysis page shows analysis entry and history panel after login', async ({ page }) => {
    await login(page);

    const stockInput = page.getByPlaceholder('输入股票代码或名称，如 600519、贵州茅台、AAPL');
    await expect(stockInput).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('link', { name: '分析' })).toBeVisible();
    await expect(page.getByRole('link', { name: '问股' })).toBeVisible();
    await expect(page.getByText('历史分析')).toBeVisible();

    await stockInput.fill('600519');
    const analyzeButton = page.getByRole('button', { name: '分析', exact: true });
    await expect(analyzeButton).toBeVisible();
  });

  test('chat page allows entering a question and starts a request', async ({ page }) => {
    await login(page);

    // Navigate to chat page by clicking the link
    await page.getByRole('link', { name: '问股' }).click();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1000);

    await expect(page.getByTestId('chat-workspace')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('chat-session-list-scroll')).toBeVisible();
    await expect(page.getByTestId('chat-message-scroll')).toBeVisible();

    const input = page.getByPlaceholder(/分析 600519/);
    await expect(input).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('策略', { exact: true })).toBeVisible();

    const prompt = '请简要分析 600519';
    await input.fill(prompt);
    await page.getByRole('button', { name: '发送' }).click();

    await expect(page.locator('p').filter({ hasText: prompt }).last()).toBeVisible({ timeout: 5000 });
  });

  test('chat page uses accessible labels instead of native title attributes for key actions', async ({ page }) => {
    await login(page);

    await page.getByRole('link', { name: '问股' }).click();
    await page.waitForLoadState('domcontentloaded');

    const sendButton = page.getByRole('button', { name: '发送' });
    const composer = page.getByPlaceholder(/分析 600519/);

    await expect(page.getByTestId('chat-workspace')).toBeVisible({ timeout: 10_000 });
    await expect(sendButton).toBeVisible({ timeout: 10_000 });
    await expect(composer).toBeVisible({ timeout: 10_000 });

    await expect(sendButton).not.toHaveAttribute('title', /.+/);
    await expect(composer).not.toHaveAttribute('title', /.+/);
  });

  test('mobile shell exposes every main destination and navigates from calendar to market', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockAuthenticatedSession(page);
    await page.goto('/calendar');

    const mobileNav = page.getByTestId('mobile-main-nav');
    await expect(mobileNav).toBeVisible();
    for (const label of ['分析', '日历', '市场', '回测', '量化', '问股']) {
      await expect(mobileNav.getByRole('link', { name: label })).toBeVisible();
    }

    await expect(mobileNav.getByRole('link', { name: '日历' })).toHaveAttribute('aria-current', 'page');

    await mobileNav.getByRole('link', { name: '市场' }).click();
    await expect(page).toHaveURL(/\/market\/watch-list$/);
    await expect(mobileNav.getByRole('link', { name: '市场' })).toHaveAttribute('aria-current', 'page');

    const marketNav = page.getByTestId('market-mobile-nav');
    await expect(marketNav).toBeVisible();
    await expect(marketNav.getByRole('link')).toHaveCount(3);
    expect(
      await marketNav.evaluate((element) => element.scrollWidth <= element.clientWidth),
    ).toBe(true);

    await page.setViewportSize({ width: 320, height: 568 });
    for (const link of await marketNav.getByRole('link').all()) {
      await expect(link).toBeVisible();
    }
    expect(
      await marketNav.evaluate((element) => element.scrollWidth <= element.clientWidth),
    ).toBe(true);

    await page.setViewportSize({ width: 844, height: 390 });
    await expect(mobileNav).toBeHidden();
    await expect(page.getByTestId('desktop-main-nav').getByRole('link', { name: '市场' })).toBeVisible();
  });

  test('settings and theme navigation entries are removed after login', async ({ page }) => {
    await login(page);

    await expect(page.getByRole('link', { name: '设置' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '切换主题' })).toHaveCount(0);
  });
});
