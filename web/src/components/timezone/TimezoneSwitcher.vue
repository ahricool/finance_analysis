<script setup lang="ts">
import { Check, Clock3 } from 'lucide-vue-next';
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

const activeOption = computed(
  () => DISPLAY_TIMEZONES.find((option) => option.value === displayTimezone.value) ?? DISPLAY_TIMEZONES[0],
);

function setTimezone(value: DisplayTimezone) {
  store.setDisplayTimezone(value);
  open.value = false;
}

function onPointerDown(event: MouseEvent) {
  if (containerRef.value && !containerRef.value.contains(event.target as Node)) {
    open.value = false;
  }
}

onMounted(() => {
  document.addEventListener('mousedown', onPointerDown);
});

onUnmounted(() => {
  document.removeEventListener('mousedown', onPointerDown);
});
</script>

<template>
  <div
    ref="containerRef"
    class="fixed bottom-4 right-4 z-[90]"
    @mouseenter="open = true"
    @mouseleave="open = false"
  >
    <button
      type="button"
      class="inline-flex h-10 items-center gap-2 rounded-lg border border-border/70 bg-elevated/95 px-3 text-sm font-medium text-foreground shadow-soft-card-strong backdrop-blur-xl transition-colors hover:bg-hover focus:outline-none focus:ring-2 focus:ring-primary/35"
      aria-haspopup="menu"
      :aria-expanded="open"
      aria-label="切换展示时区"
      @click="open = !open"
    >
      <Clock3 class="h-4 w-4 text-primary" />
      <span class="tabular-nums">{{ activeOption.shortLabel }}</span>
    </button>

    <div
      v-if="open"
      role="menu"
      aria-label="展示时区"
      class="absolute bottom-full right-0 mb-2 w-52 rounded-lg border border-border/80 bg-elevated/96 p-1.5 text-sm shadow-soft-card-strong backdrop-blur-xl"
    >
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
        <Check v-if="displayTimezone === option.value" class="h-4 w-4 text-cyan" />
      </button>
    </div>
  </div>
</template>
