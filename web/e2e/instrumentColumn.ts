import { expect, type Locator } from '@playwright/test';

export async function expectPinnedInstrumentColumn(table: Locator, index: number, pinnedBefore = 0) {
  const viewport = table.locator('..');
  const header = table.getByRole('columnheader').nth(index);
  const cell = table.locator('tbody tr').first().getByRole('cell').nth(index);
  await viewport.evaluate(el => { el.scrollLeft = el.scrollWidth; });
  await expect.poll(() => viewport.evaluate(el => el.scrollLeft)).toBeGreaterThan(0);
  expect((await cell.boundingBox())!.width).toBeLessThan((await viewport.boundingBox())!.width * 0.65);
  const left = await viewport.evaluate(el => el.getBoundingClientRect().left + el.clientLeft);
  let offset = 0;
  for (let i = index - pinnedBefore; i < index; i++) {
    offset += (await table.getByRole('columnheader').nth(i).boundingBox())!.width;
  }
  for (const pinned of [header, cell]) {
    await expect.poll(() => pinned.evaluate(el => el.getBoundingClientRect().left)).toBeCloseTo(left + offset, 0);
  }
  await viewport.evaluate(el => { el.scrollLeft = 0; });
}
