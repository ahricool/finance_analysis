import { ref, watch, type Ref } from 'vue';

const viewportMargin = { rootMargin: '400px 0px', scrollMargin: '400px 0px' };
const listeners = new Map<Element, { intersecting: boolean; update: (visible: boolean) => void }>();
let observer: IntersectionObserver | undefined;
function visibilityChanged() {
  for (const entry of listeners.values()) entry.update(entry.intersecting && !document.hidden);
}

/** Share the same prefetch margin across tables, scrolling dialogs and virtual lists. */
export function useNearViewport(element: Ref<HTMLElement | null>) {
  const near = ref(false);
  watch(element, (target, _, cleanup) => {
    near.value = false;
    if (!target) return;
    if (!observer) {
      observer = new IntersectionObserver(entries => {
        for (const entry of entries) {
          const listener = listeners.get(entry.target);
          if (listener) {
            listener.intersecting = entry.isIntersecting;
            listener.update(entry.isIntersecting && !document.hidden);
          }
        }
      }, viewportMargin);
      document.addEventListener('visibilitychange', visibilityChanged);
    }
    listeners.set(target, { intersecting: false, update: visible => { near.value = visible; } });
    observer.observe(target);
    cleanup(() => {
      observer?.unobserve(target);
      listeners.delete(target);
      if (!listeners.size) {
        observer?.disconnect();
        observer = undefined;
        document.removeEventListener('visibilitychange', visibilityChanged);
      }
    });
  }, { flush: 'post' });
  return near;
}
