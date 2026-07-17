<script setup lang="ts">
import { Check, Clock3, Ellipsis } from 'lucide-vue-next';
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { storeToRefs } from 'pinia';
import {
  DISPLAY_TIMEZONES,
  type DisplayTimezone,
  useTimezoneStore,
} from '@/stores/timezoneStore';
import { cn } from '@/utils/cn';

const store = useTimezoneStore();
const { displayTimezone } = storeToRefs(store);
const open = ref(false);
const containerRef = ref<HTMLElement | null>(null);
let closeTimer: ReturnType<typeof window.setTimeout> | undefined;

const CLOSE_DELAY_MS = 180;

const activeOption = computed(
  () => DISPLAY_TIMEZONES.find((option) => option.value === displayTimezone.value) ?? DISPLAY_TIMEZONES[0],
);

function setTimezone(value: DisplayTimezone) {
  store.setDisplayTimezone(value);
  closeMenu();
}

function clearCloseTimer() {
  if (closeTimer !== undefined) {
    window.clearTimeout(closeTimer);
    closeTimer = undefined;
  }
}

function openMenu() {
  clearCloseTimer();
  open.value = true;
}

function closeMenu() {
  clearCloseTimer();
  open.value = false;
}

function scheduleClose() {
  clearCloseTimer();
  closeTimer = window.setTimeout(() => {
    open.value = false;
    closeTimer = undefined;
  }, CLOSE_DELAY_MS);
}

function toggleMenu() {
  clearCloseTimer();
  open.value = !open.value;
}

function onPointerDown(event: MouseEvent) {
  if (containerRef.value && !containerRef.value.contains(event.target as Node)) {
    closeMenu();
  }
}

function onFocusOut(event: FocusEvent) {
  if (!containerRef.value?.contains(event.relatedTarget as Node | null)) {
    closeMenu();
  }
}

onMounted(() => {
  document.addEventListener('mousedown', onPointerDown);
});

onUnmounted(() => {
  clearCloseTimer();
  document.removeEventListener('mousedown', onPointerDown);
});
</script>

<template>
  <div
    ref="containerRef"
    class="fixed bottom-[calc(4.75rem+env(safe-area-inset-bottom))] right-3 z-[90] md:bottom-4 md:right-4"
    @mouseenter="openMenu"
    @mouseleave="scheduleClose"
    @focusin="openMenu"
    @focusout="onFocusOut"
  >
    <button
      type="button"
      class="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-border/70 bg-elevated/95 text-foreground shadow-soft-card-strong backdrop-blur-xl transition-colors hover:bg-hover focus:outline-none focus:ring-2 focus:ring-primary/35"
      aria-haspopup="menu"
      :aria-expanded="open"
      aria-label="打开设置菜单"
      @click="toggleMenu"
    >
      <Ellipsis class="h-5 w-5 text-primary" />
    </button>

    <div
      v-if="open"
      class="absolute bottom-full right-0 w-64 pb-2"
      @mouseenter="openMenu"
      @mouseleave="scheduleClose"
    >
      <div
        role="menu"
        aria-label="设置"
        class="rounded-lg border border-border/80 bg-elevated/96 p-2 text-sm shadow-soft-card-strong backdrop-blur-xl"
      >
        <div class="mb-1 flex items-center justify-between px-2 py-1.5">
          <span class="text-xs font-medium text-muted-text">展示时区</span>
          <span class="inline-flex items-center gap-1 rounded-md bg-cyan/10 px-2 py-0.5 text-xs font-medium text-cyan">
            <Clock3 class="h-3.5 w-3.5" />
            {{ activeOption.shortLabel }}
          </span>
        </div>

        <button
          v-for="option in DISPLAY_TIMEZONES"
          :key="option.value"
          type="button"
          role="menuitemradio"
          :aria-checked="displayTimezone === option.value"
          :class="
            cn(
              'flex w-full items-center justify-between rounded-md px-3 py-2 text-left transition-colors',
              displayTimezone === option.value
                ? 'bg-cyan/10 text-foreground'
                : 'text-secondary-text hover:bg-hover hover:text-foreground',
            )
          "
          @click="setTimezone(option.value)"
        >
          <span>
            <span class="block font-medium">{{ option.label }}</span>
            <span class="block text-xs text-muted-text">{{ option.value }}</span>
          </span>
          <Check
            v-if="displayTimezone === option.value"
            class="h-4 w-4 text-cyan"
          />
        </button>
      </div>
    </div>
  </div>
</template>
