import type { ObjectDirective } from 'vue';

type FitState = { observer: ResizeObserver; frame: number; schedule: () => void };
const states = new WeakMap<HTMLElement, FitState>();

function fitLabel(tile: HTMLElement) {
  const labels = tile.querySelector<HTMLElement>('.heatmap-labels');
  if (!labels || !tile.clientWidth || !tile.clientHeight) return;
  const style = getComputedStyle(tile);
  const height = tile.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
  const change = labels.querySelector<HTMLElement>('.heatmap-stock-change');
  labels.style.visibility = 'hidden';
  // Try both lines first, then spend all available space on the stock identity.
  for (const showChange of [true, false]) {
    if (change) change.style.display = showChange ? '' : 'none';
    for (let size = 16; size >= 5; size--) {
      tile.style.setProperty('--heatmap-font-size', `${size}px`);
      if (labels.getBoundingClientRect().height <= height && labels.scrollWidth <= labels.clientWidth) {
        labels.style.visibility = 'visible';
        return;
      }
    }
  }
}

export const vFitLabel: ObjectDirective<HTMLElement> = {
  mounted(tile) {
    const state: FitState = {
      observer: new ResizeObserver(() => state.schedule()),
      frame: 0,
      schedule() {
        cancelAnimationFrame(state.frame);
        state.frame = requestAnimationFrame(() => fitLabel(tile));
      },
    };
    states.set(tile, state);
    state.observer.observe(tile);
    state.schedule();
    // Font loading can change wrapping without changing the tile's dimensions.
    void document.fonts?.ready.then(() => {
      if (states.get(tile) === state) state.schedule();
    });
  },
  updated(tile) { states.get(tile)?.schedule(); },
  unmounted(tile) {
    const state = states.get(tile);
    state?.observer.disconnect();
    if (state) cancelAnimationFrame(state.frame);
    states.delete(tile);
  },
};
