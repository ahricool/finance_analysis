<script setup lang="ts">
import { Check, Monitor, Moon, Sun } from 'lucide-vue-next';
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { cn } from '@/utils/cn';
import { resolvedTheme, theme, useTheme } from '@/composables/useTheme';

type ThemeOption = 'light' | 'dark' | 'system';
type ThemeToggleVariant = 'default' | 'nav';

const props = withDefaults(
  defineProps<{
    variant?: ThemeToggleVariant;
    collapsed?: boolean;
  }>(),
  { variant: 'default', collapsed: false },
);

const THEME_OPTIONS: Array<{ value: ThemeOption; label: string; icon: typeof Sun }> = [
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'dark', label: '深色', icon: Moon },
  { value: 'system', label: '跟随系统', icon: Monitor },
];

function resolveThemeLabel(t: string | undefined) {
  switch (t) {
    case 'light':
      return '浅色';
    case 'dark':
      return '深色';
    default:
      return '跟随系统';
  }
}

const { setTheme } = useTheme();
const open = ref(false);
const containerRef = ref<HTMLElement | null>(null);

const activeTheme = computed(() => (theme.value as ThemeOption) ?? 'system');
const visualTheme = computed(() => resolvedTheme.value ?? 'dark');
const TriggerIcon = computed(() => (visualTheme.value === 'light' ? Sun : Moon));
const isNavVariant = computed(() => props.variant === 'nav');

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
  <div ref="containerRef" class="relative">
    <button
      type="button"
      :data-state="open ? 'open' : 'closed'"
      :class="
        cn(
          isNavVariant
            ? 'group relative flex h-12 w-full select-none items-center gap-3 rounded-xl border border-transparent px-4 text-sm text-secondary-text transition-all duration-300 hover:-translate-y-0.5 hover:bg-hover hover:text-foreground data-[state=open]:border-primary/25 data-[state=open]:bg-cyan/10 data-[state=open]:text-foreground'
            : 'inline-flex h-10 items-center gap-2 rounded-xl border border-border/80 bg-card/90 px-3 text-sm text-secondary-text shadow-soft-card transition-all hover:-translate-y-0.5 hover:border-primary/25 hover:bg-card hover:text-foreground',
          isNavVariant && collapsed ? 'justify-center px-2' : '',
        )
      "
      aria-haspopup="menu"
      :aria-expanded="open"
      aria-label="切换主题"
      @click="open = !open"
    >
      <component :is="TriggerIcon" :class="cn('shrink-0', isNavVariant ? 'h-5 w-5' : 'h-4 w-4')" />
      <span v-if="isNavVariant" class="truncate text-[1.02rem] font-medium">{{
        collapsed ? '' : '主题'
      }}</span>
      <span v-else class="hidden sm:inline">{{ resolveThemeLabel(activeTheme) }}</span>
    </button>

    <div
      v-if="open"
      role="menu"
      aria-label="主题模式"
      :class="
        cn(
          'z-[100] min-w-[8rem] overflow-hidden rounded-2xl border border-border/80 bg-elevated/96 p-1.5 shadow-soft-card-strong backdrop-blur-xl',
          isNavVariant ? 'absolute bottom-full left-0 mb-2 w-max min-w-[9rem]' : 'absolute right-0 mt-2',
        )
      "
    >
      <button
        v-for="opt in THEME_OPTIONS"
        :key="opt.value"
        type="button"
        role="menuitemradio"
        :aria-checked="activeTheme === opt.value"
        :class="
          cn(
            'flex w-full items-center justify-between rounded-xl px-3 py-2 text-sm transition-colors',
            activeTheme === opt.value
              ? 'bg-cyan/10 text-foreground'
              : 'text-secondary-text hover:bg-hover hover:text-foreground',
          )
        "
        @click="
          setTheme(opt.value);
          open = false;
        "
      >
        <span class="flex items-center gap-2">
          <component :is="opt.icon" class="h-4 w-4" />
          {{ opt.label }}
        </span>
        <Check v-if="activeTheme === opt.value" class="h-4 w-4 text-cyan" />
      </button>
    </div>
  </div>
</template>
