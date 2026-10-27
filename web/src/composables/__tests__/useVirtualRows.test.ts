import { describe, expect, it } from 'vitest';
import { ref } from 'vue';
import { useVirtualRows, virtualWindow } from '../useVirtualRows';

describe('virtual table rows', () => {
  it('starts at the top with the full window and spacer below', () => {
    expect(virtualWindow(1000, 0)).toEqual({ start: 0, end: 28, topSpace: 0, bottomSpace: 972 * 64 });
  });

  it('keeps overscan rows above the first visible row', () => {
    // 80px header + 20 rows scrolled → row 20 visible, window starts 8 rows earlier.
    expect(virtualWindow(1000, 80 + 20 * 64)).toMatchObject({ start: 12, end: 40, topSpace: 12 * 64 });
  });

  it('clamps the window to the final rows', () => {
    expect(virtualWindow(500, 1_000_000)).toEqual({ start: 472, end: 500, topSpace: 472 * 64, bottomSpace: 0 });
  });

  it('renders every row below the threshold and windows above it', () => {
    const items = ref(Array.from({ length: 10 }, (_, index) => index));
    const virtual = useVirtualRows(items, { threshold: 20 });
    expect(virtual.virtual.value).toBe(false);
    expect(virtual.rows.value).toHaveLength(10);
    items.value = Array.from({ length: 100 }, (_, index) => index);
    virtual.scrollTop.value = 80 + 50 * 64;
    expect(virtual.virtual.value).toBe(true);
    expect(virtual.rows.value[0]).toBe(42);
    expect(virtual.range.value.bottomSpace).toBe((100 - 70) * 64);
  });
});
