import { expect, test, type Page } from '@playwright/test';

async function setup(page: Page, theme: 'light' | 'dark') {
  await page.addInitScript(value => localStorage.setItem('theme', value), theme);
  await page.clock.install({ time: new Date('2026-10-30T08:00:00Z') });
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ json: path.endsWith('/auth/status')
      ? { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', email: 'tester@example.test' } }
      : { items: [], total: 0, has_more: false, next_cursor: null } });
  });
  await page.goto('/timeline?market=US');
  await expect(page.getByTestId('investment-timeline')).toBeVisible();
  // Exercise a real scrollbar, including empty-data screens.
  await page.addStyleTag({ content: 'main { min-height: 150vh; }' });
}
async function geometry(page: Page) {
  return page.evaluate(() => {
    const header = document.querySelector('[data-testid="shell-header-content"]')!.getBoundingClientRect();
    const trigger = document.querySelector('[aria-label="重要性"]')!.getBoundingClientRect();
    return { headerX: header.x, headerWidth: header.width, triggerX: trigger.x, triggerWidth: trigger.width,
      overflow: document.body.style.overflow, padding: document.body.style.paddingRight, scrollX };
  });
}
for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  for (const theme of ['light', 'dark'] as const) {
    test(`themed filters never shift the document at ${width}px ${theme}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 }); await setup(page, theme);
      const trigger = page.getByRole('combobox', { name: '重要性', exact: true });
      const before = await geometry(page);
      const brand = await page.getByRole('button', { name: '今天', exact: true }).evaluate(el => getComputedStyle(el).backgroundColor);
      await trigger.click();
      await expect(page.getByRole('listbox')).toBeVisible();
      await expect(page.getByRole('option', { name: '全部重要性', exact: true }).locator('svg')).toHaveCSS('color', brand);
      expect(await geometry(page)).toEqual(before);
      await page.getByRole('option', { name: 'High 及以上', exact: true }).click();
      await expect(page.getByRole('listbox')).toHaveCount(0);
      await expect(trigger).toContainText('High 及以上');
      expect(await geometry(page)).toEqual(before);
      await trigger.focus(); await trigger.press('ArrowDown');
      await expect(page.getByRole('listbox')).toBeVisible();
      await page.keyboard.press('Escape'); await expect(trigger).toBeFocused();
      expect(await geometry(page)).toEqual(before);
      await trigger.click(); await page.getByRole('option', { name: '全部重要性', exact: true }).click();
      await expect(trigger).toContainText('全部重要性');
      expect(await geometry(page)).toEqual(before);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
  }
}
for (const theme of ['light', 'dark'] as const) {
  test(`calendar month/year selects and selected day use the theme without scroll locking in ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 }); await setup(page, theme);
    const brand = await page.getByRole('button', { name: '今天', exact: true }).evaluate(el => getComputedStyle(el).backgroundColor);
    const before = await geometry(page);
    await page.getByTestId('investment-timeline').getByRole('button', { name: /2026年10月30日/ }).click();
    const calendar = page.locator('[data-slot="calendar"]'); await expect(calendar).toBeVisible();
    const selected = calendar.locator('[data-slot="calendar-cell-trigger"][data-selected]');
    await expect(selected).toHaveCSS('background-color', brand);
    const month = page.getByRole('combobox', { name: '月份', exact: true });
    await month.click(); await expect(page.getByRole('listbox')).toBeVisible();
    expect(await geometry(page)).toEqual(before);
    await page.getByRole('option').filter({ hasText: /^9月$/ }).click();
    await expect(calendar).toBeVisible(); await expect(month).toContainText('9月');
    const year = page.getByRole('combobox', { name: '年份', exact: true });
    await year.click(); await page.getByRole('option', { name: '2025年', exact: true }).click();
    await expect(calendar).toBeVisible(); await expect(year).toContainText('2025年');
    expect(await geometry(page)).toEqual(before);
    await page.keyboard.press('Escape'); await expect(calendar).toHaveCount(0);
    expect(await geometry(page)).toEqual(before);
  });
}
