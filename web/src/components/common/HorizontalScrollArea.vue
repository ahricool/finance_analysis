<script setup lang="ts">
import { cn } from '@/utils/cn';
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';

const props = withDefaults(
  defineProps<{
    ariaLabel?: string;
    class?: string;
    viewportClassName?: string;
    hintText?: string;
    showHint?: boolean;
    showTopScrollbar?: boolean;
  }>(),
  {
    ariaLabel: '可横向滚动内容',
    hintText: '可横向滚动：拖动上方滚动条，或按住 Shift 滚动鼠标滚轮。',
    showHint: true,
    showTopScrollbar: true,
  },
);

const topScrollEl = ref<HTMLDivElement | null>(null);
const viewportEl = ref<HTMLDivElement | null>(null);
const isOverflowing = ref(false);
const scrollWidth = ref(0);
const topScrollbarLabel = computed(() => `${props.ariaLabel}顶部横向滚动条`);

let resizeObserver: ResizeObserver | null = null;
let mutationObserver: MutationObserver | null = null;
let resizeObservedChildren = new Set<Element>();
let measureFrame = 0;
let isSyncingScroll = false;

function measureOverflow() {
  const viewport = viewportEl.value;
  if (!viewport) return;

  const nextScrollWidth = Math.ceil(viewport.scrollWidth);
  const nextClientWidth = Math.ceil(viewport.clientWidth);
  scrollWidth.value = nextScrollWidth;
  isOverflowing.value = nextScrollWidth - nextClientWidth > 1;

  if (topScrollEl.value && topScrollEl.value.scrollLeft !== viewport.scrollLeft) {
    topScrollEl.value.scrollLeft = viewport.scrollLeft;
  }
}

function scheduleMeasure() {
  if (measureFrame) return;
  measureFrame = window.requestAnimationFrame(() => {
    measureFrame = 0;
    measureOverflow();
  });
}

function observeScrollableChildren() {
  const viewport = viewportEl.value;
  if (!resizeObserver || !viewport) return;

  for (const child of resizeObservedChildren) {
    resizeObserver.unobserve(child);
  }
  resizeObservedChildren = new Set(Array.from(viewport.children));
  for (const child of resizeObservedChildren) {
    resizeObserver.observe(child);
  }
}

function syncScroll(source: HTMLDivElement, target: HTMLDivElement | null) {
  if (!target || isSyncingScroll) return;
  isSyncingScroll = true;
  target.scrollLeft = source.scrollLeft;
  window.requestAnimationFrame(() => {
    isSyncingScroll = false;
  });
}

function handleTopScroll() {
  const top = topScrollEl.value;
  if (!top) return;
  syncScroll(top, viewportEl.value);
}

function handleViewportScroll() {
  const viewport = viewportEl.value;
  if (!viewport) return;
  syncScroll(viewport, topScrollEl.value);
}

function scrollHorizontally(delta: number) {
  const viewport = viewportEl.value;
  if (!viewport || !isOverflowing.value || delta === 0) return;
  viewport.scrollLeft += delta;
  if (topScrollEl.value) {
    topScrollEl.value.scrollLeft = viewport.scrollLeft;
  }
}

function handleViewportWheel(event: WheelEvent) {
  if (!event.shiftKey) return;
  const delta = event.deltaY || event.deltaX;
  if (delta === 0) return;
  event.preventDefault();
  scrollHorizontally(delta);
}

function handleTopWheel(event: WheelEvent) {
  const delta = event.deltaY || event.deltaX;
  if (delta === 0) return;
  event.preventDefault();
  scrollHorizontally(delta);
}

onMounted(() => {
  const viewport = viewportEl.value;
  if (!viewport) return;

  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      observeScrollableChildren();
      scheduleMeasure();
    });
    resizeObserver.observe(viewport);
    observeScrollableChildren();
  }

  if (typeof MutationObserver !== 'undefined') {
    mutationObserver = new MutationObserver(() => {
      observeScrollableChildren();
      scheduleMeasure();
    });
    mutationObserver.observe(viewport, {
      attributes: true,
      childList: true,
      subtree: true,
    });
  }

  window.addEventListener('resize', scheduleMeasure);
  void nextTick(scheduleMeasure);
});

onBeforeUnmount(() => {
  if (measureFrame) {
    window.cancelAnimationFrame(measureFrame);
  }
  window.removeEventListener('resize', scheduleMeasure);
  mutationObserver?.disconnect();
  resizeObserver?.disconnect();
});
</script>

<template>
  <div
    :class="cn('horizontal-scroll-area min-w-0', props.class)"
    :data-overflowing="isOverflowing ? 'true' : 'false'"
  >
    <div v-if="showHint && isOverflowing" class="horizontal-scroll-area__hint" aria-live="polite">
      {{ hintText }}
    </div>
    <div
      v-show="showTopScrollbar && isOverflowing"
      ref="topScrollEl"
      class="horizontal-scroll-area__top-scroll"
      data-scroll-area="horizontal"
      tabindex="0"
      :aria-label="topScrollbarLabel"
      @scroll.passive="handleTopScroll"
      @wheel="handleTopWheel"
    >
      <div class="horizontal-scroll-area__top-scroll-spacer" :style="{ width: `${scrollWidth}px` }" />
    </div>
    <div
      ref="viewportEl"
      :class="cn('horizontal-scroll-area__viewport', viewportClassName)"
      data-scroll-area="horizontal"
      tabindex="0"
      :aria-label="ariaLabel"
      @scroll.passive="handleViewportScroll"
      @wheel="handleViewportWheel"
    >
      <slot />
    </div>
  </div>
</template>
