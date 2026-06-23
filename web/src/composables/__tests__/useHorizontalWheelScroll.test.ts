import { describe, expect, it, vi } from 'vitest';
import { useHorizontalWheelScroll } from '@/composables/useHorizontalWheelScroll';

function createWheelEvent(
  target: HTMLElement,
  overrides: Partial<{ deltaY: number; deltaX: number }> = {},
): WheelEvent & { preventDefault: ReturnType<typeof vi.fn> } {
  const preventDefault = vi.fn();
  return {
    currentTarget: target,
    deltaY: 0,
    deltaX: 0,
    preventDefault,
    ...overrides,
  } as WheelEvent & { preventDefault: ReturnType<typeof vi.fn> };
}

describe('useHorizontalWheelScroll', () => {
  it('scrolls horizontally when vertical wheel movement is dominant', () => {
    const element = document.createElement('div');
    Object.defineProperty(element, 'scrollWidth', { value: 200, configurable: true });
    Object.defineProperty(element, 'clientWidth', { value: 100, configurable: true });
    element.scrollLeft = 0;

    const { onWheel } = useHorizontalWheelScroll();
    const event = createWheelEvent(element, { deltaY: 40, deltaX: 0 });

    onWheel(event);

    expect(event.preventDefault).toHaveBeenCalled();
    expect(element.scrollLeft).toBe(40);
  });

  it('does nothing when content fits within the container', () => {
    const element = document.createElement('div');
    Object.defineProperty(element, 'scrollWidth', { value: 100, configurable: true });
    Object.defineProperty(element, 'clientWidth', { value: 100, configurable: true });
    element.scrollLeft = 0;

    const { onWheel } = useHorizontalWheelScroll();
    const event = createWheelEvent(element, { deltaY: 40, deltaX: 0 });

    onWheel(event);

    expect(event.preventDefault).not.toHaveBeenCalled();
    expect(element.scrollLeft).toBe(0);
  });
});
