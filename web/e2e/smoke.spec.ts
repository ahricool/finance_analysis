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

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
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

    await expect(page.getByTestId('conversation-workspace')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('conversation-list-scroll')).toBeVisible();
    await expect(page.getByTestId('conversation-message-scroll')).toBeVisible();

    const input = page.getByPlaceholder(/分析 600519/);
    await expect(input).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('策略', { exact: true })).toBeVisible();

    const prompt = '请简要分析 600519';
    await input.fill(prompt);
    await page.getByRole('button', { name: '发送' }).click();

    await expect(page.locator('p').filter({ hasText: prompt }).last()).toBeVisible({
      timeout: 5000,
    });
  });

  test('chat page uses accessible labels instead of native title attributes for key actions', async ({
    page,
  }) => {
    await login(page);

    await page.getByRole('link', { name: '问股' }).click();
    await page.waitForLoadState('domcontentloaded');

    const sendButton = page.getByRole('button', { name: '发送' });
    const composer = page.getByPlaceholder(/分析 600519/);

    await expect(page.getByTestId('conversation-workspace')).toBeVisible({ timeout: 10_000 });
    await expect(sendButton).toBeVisible({ timeout: 10_000 });
    await expect(composer).toBeVisible({ timeout: 10_000 });

    await expect(sendButton).not.toHaveAttribute('title', /.+/);
    await expect(composer).not.toHaveAttribute('title', /.+/);
  });

  test('mobile shell exposes primary destinations, More sheet, and market navigation', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockAuthenticatedSession(page);
    await page.goto('/calendar');

    const mobileNav = page.getByTestId('mobile-main-nav');
    await expect(mobileNav).toBeVisible();
    for (const label of ['分析', '日历', '市场', '问股']) {
      await expect(mobileNav.getByRole('link', { name: label })).toBeVisible();
    }
    await expect(mobileNav.getByRole('button', { name: '更多' })).toBeVisible();

    await mobileNav.getByRole('button', { name: '更多' }).click();
    const moreSheet = page.getByRole('dialog', { name: '更多功能' });
    await expect(moreSheet).toBeVisible();
    for (const label of ['回测', '量化', '任务', '个人中心']) {
      await expect(moreSheet.getByRole('link', { name: label })).toBeVisible();
    }
    await moreSheet.getByRole('link', { name: '回测' }).click();
    await expect(page).toHaveURL(/\/market\/backtests$/);
    await expect(moreSheet).toBeHidden();

    await page.goto('/tasks/runs');
    await expect(mobileNav.getByRole('button', { name: '更多' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await mobileNav.getByRole('button', { name: '更多' }).click();
    await expect(
      page.getByRole('dialog', { name: '更多功能' }).getByRole('link', { name: '任务' }),
    ).toHaveAttribute('aria-current', 'page');
    await page.keyboard.press('Escape');

    await page.goto('/calendar');

    await expect(mobileNav.getByRole('link', { name: '日历' })).toHaveAttribute(
      'aria-current',
      'page',
    );

    await mobileNav.getByRole('link', { name: '市场' }).click();
    await expect(page).toHaveURL(/\/market\/watch-list$/);
    await expect(mobileNav.getByRole('link', { name: '市场' })).toHaveAttribute(
      'aria-current',
      'page',
    );

    const marketNav = page.getByTestId('module-tabs');
    await expect(marketNav).toBeVisible();
    await expect(marketNav.getByRole('tab')).toHaveCount(3);
    await expect(marketNav.locator('[data-reka-scroll-area-viewport]')).toBeVisible();

    await page.setViewportSize({ width: 360, height: 800 });
    for (const link of await marketNav.getByRole('tab').all()) {
      await expect(link).toBeVisible();
    }

    await page.setViewportSize({ width: 844, height: 390 });
    await expect(mobileNav).toBeHidden();
    await expect(
      page.getByTestId('desktop-main-nav').getByRole('link', { name: '市场' }),
    ).toBeVisible();
  });

  test('shell remains usable without horizontal overflow at all required breakpoints', async ({
    page,
  }) => {
    await mockAuthenticatedSession(page);
    const viewports = [
      { width: 360, height: 800 },
      { width: 375, height: 812 },
      { width: 390, height: 844 },
      { width: 430, height: 932 },
      { width: 768, height: 1024 },
      { width: 1280, height: 800 },
    ];

    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await page.goto('/calendar');
      await expect(page.getByRole('heading', { name: '日历记录' })).toBeVisible();
      if (viewport.width < 768) {
        await expect(page.getByTestId('mobile-main-nav')).toBeVisible();
      } else {
        await expect(page.getByTestId('desktop-main-nav')).toBeVisible();
      }
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
    }
  });

  test('date, time, datetime, select, combobox, dialog, and popover controls are operable', async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    await page.setViewportSize({ width: 390, height: 844 });
    await mockAuthenticatedSession(page);
    await page.goto('/calendar');

    const displayDateButton = page.getByRole('button', { name: '展示日期' });
    const previousDisplay = await displayDateButton.textContent();
    await displayDateButton.click();
    const calendar = page.locator('[data-slot="calendar"]').last();
    await expect(calendar).toBeVisible();
    const alternateDate = calendar
      .locator('[data-slot="calendar-cell-trigger"]:not([data-selected]):not([data-disabled])')
      .first();
    await alternateDate.click();
    await expect(calendar).toBeHidden();
    expect(await displayDateButton.textContent()).not.toBe(previousDisplay);

    await page.getByTestId('add-finance-event').click();
    const eventDialog = page.getByRole('dialog', { name: '新增财经事件' });
    await expect(eventDialog).toBeVisible();
    const eventType = eventDialog.getByRole('combobox', { name: '事件类型 *' });
    await eventType.click();
    await page.waitForTimeout(100);
    expect(pageErrors).toEqual([]);
    const comboboxPopover = page.locator('[data-slot="popover-content"]').last();
    await expect(comboboxPopover).toBeVisible();
    await comboboxPopover.locator('[data-slot="command-input"]').fill('财报');
    await page.getByRole('option', { name: /财报/ }).click();
    await expect(eventType).toContainText('财报');
    await eventDialog.getByRole('button', { name: '取消' }).click();
    await expect(eventDialog).toBeHidden();

    await page.getByTestId('add-calendar-entry').click();
    const entryDialog = page.getByRole('dialog', { name: '新增日历记录' });
    await expect(entryDialog).toBeVisible();
    const dateTimeButton = entryDialog.getByRole('button', { name: '记录时间 *' });
    await dateTimeButton.click();
    const dateTimeDialog = page.getByRole('dialog', { name: '选择日期和时间' });
    await expect(dateTimeDialog).toBeVisible();
    const timeButton = dateTimeDialog.getByRole('button', { name: '时间', exact: true });
    await timeButton.click();
    const timePopover = page.locator('[data-slot="popover-content"]').last();
    const hourSelect = timePopover.getByRole('combobox', { name: '小时' });
    const minuteSelect = timePopover.getByRole('combobox', { name: '分钟' });
    await hourSelect.click();
    await page.getByRole('option', { name: '10', exact: true }).click();
    await minuteSelect.click();
    await page.getByRole('option', { name: '30', exact: true }).click();
    await timePopover.getByRole('button', { name: '确认' }).click();
    await dateTimeDialog.getByRole('button', { name: '确认' }).click();
    await expect(dateTimeButton).toContainText('10:30');
    await entryDialog.getByRole('button', { name: '取消' }).click();
    expect(pageErrors).toEqual([]);
  });

  test('settings and theme navigation entries are removed after login', async ({ page }) => {
    await login(page);

    await expect(page.getByRole('link', { name: '设置' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '切换主题' })).toHaveCount(0);
  });
});
