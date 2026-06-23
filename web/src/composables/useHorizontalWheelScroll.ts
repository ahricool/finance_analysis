function scrollHorizontallyFromWheel(element: HTMLElement, event: WheelEvent): void {
  if (element.scrollWidth <= element.clientWidth) return;
  if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;

  event.preventDefault();
  element.scrollLeft += event.deltaY;
}

/**
 * Map vertical mouse wheel movement to horizontal scroll when content overflows.
 * Useful for wide tables on desktops without a horizontal scroll wheel.
 */
export function useHorizontalWheelScroll() {
  function onWheel(event: WheelEvent) {
    const element = event.currentTarget;
    if (element instanceof HTMLElement) {
      scrollHorizontallyFromWheel(element, event);
    }
  }

  function onDelegatedWheel(event: WheelEvent) {
    const element = (event.target as Element | null)?.closest('.table-scroll-x');
    if (element instanceof HTMLElement) {
      scrollHorizontallyFromWheel(element, event);
    }
  }

  return { onWheel, onDelegatedWheel };
}
