<script setup lang="ts">
import { cn } from '@/utils/cn';
import { computed, nextTick, onUnmounted, ref, useId, watch } from 'vue';

const props = withDefaults(
  defineProps<{
    content?: unknown;
    side?: 'top' | 'bottom';
    focusable?: boolean;
    class?: string;
    contentClass?: string;
  }>(),
  {
    side: 'top',
    focusable: false,
    class: '',
    contentClass: '',
  },
);

const open = ref(false);
const triggerRef = ref<HTMLSpanElement | null>(null);
const tooltipRef = ref<HTMLSpanElement | null>(null);
const resolvedSide = ref<'top' | 'bottom'>(props.side);
const pos = ref({ top: 0, left: 0 });
const tooltipId = useId();

const hasContent = computed(() => props.content !== undefined && props.content !== null && props.content !== '');

function updatePosition() {
  const trigger = triggerRef.value;
  const tooltip = tooltipRef.value;
  if (!trigger || !tooltip) return;

  const triggerRect = trigger.getBoundingClientRect();
  const tooltipRect = tooltip.getBoundingClientRect();
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const gap = 10;
  const margin = 8;

  let nextSide = props.side;
  let top =
    props.side === 'top' ? triggerRect.top - tooltipRect.height - gap : triggerRect.bottom + gap;

  if (props.side === 'top' && top < margin) {
    nextSide = 'bottom';
    top = triggerRect.bottom + gap;
  } else if (
    props.side === 'bottom' &&
    top + tooltipRect.height > viewportHeight - margin
  ) {
    nextSide = 'top';
    top = triggerRect.top - tooltipRect.height - gap;
  }

  let left = triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2;
  left = Math.max(margin, Math.min(left, viewportWidth - tooltipRect.width - margin));
  top = Math.max(margin, Math.min(top, viewportHeight - tooltipRect.height - margin));

  resolvedSide.value = nextSide;
  pos.value = { top, left };
}

function onViewportChange() {
  if (open.value) updatePosition();
}

watch(open, async (v) => {
  if (v) {
    window.addEventListener('resize', onViewportChange);
    window.addEventListener('scroll', onViewportChange, true);
    await nextTick();
    requestAnimationFrame(() => updatePosition());
  } else {
    window.removeEventListener('resize', onViewportChange);
    window.removeEventListener('scroll', onViewportChange, true);
  }
});

onUnmounted(() => {
  window.removeEventListener('resize', onViewportChange);
  window.removeEventListener('scroll', onViewportChange, true);
});

function onKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    open.value = false;
  }
}
</script>

<template>
  <template v-if="!hasContent">
    <span ref="triggerRef" :class="cn('inline-flex', props.class)">
      <slot />
    </span>
  </template>
  <template v-else>
    <span
      ref="triggerRef"
      :class="cn('inline-flex', props.class)"
      :tabindex="focusable ? 0 : undefined"
      :aria-describedby="open ? tooltipId : undefined"
      @mouseenter="open = true"
      @mouseleave="open = false"
      @focus="open = true"
      @blur="open = false"
      @keydown="onKeyDown"
    >
      <slot />
    </span>

    <Teleport to="body">
      <span
        v-show="open"
        :id="tooltipId"
        ref="tooltipRef"
        role="tooltip"
        :style="{ position: 'fixed', top: `${pos.top}px`, left: `${pos.left}px` }"
        :class="
          cn(
            'pointer-events-none z-[120] min-w-max max-w-[18rem] rounded-xl border border-border/70 bg-elevated/95 px-3 py-1.5 text-xs leading-5 text-foreground shadow-[0_16px_40px_rgba(3,8,20,0.18)] backdrop-blur-xl',
            resolvedSide === 'top' ? 'origin-bottom' : 'origin-top',
            contentClass,
          )
        "
      >
        {{ content }}
      </span>
    </Teleport>
  </template>
</template>
