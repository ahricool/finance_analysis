<script setup lang="ts">
import { cn } from '@/utils/cn';
import { computed } from 'vue';

type Variant =
  | 'primary'
  | 'secondary'
  | 'outline'
  | 'ghost'
  | 'gradient'
  | 'danger'
  | 'danger-subtle'
  | 'settings-primary'
  | 'settings-secondary'
  | 'action-primary'
  | 'action-secondary'
  | 'home-action-ai'
  | 'home-action-report';

type Size = 'xsm' | 'sm' | 'md' | 'lg' | 'xl';

const BUTTON_SIZE_STYLES: Record<Size, string> = {
  xsm: 'h-6 rounded-lg px-2 text-sm',
  sm: 'h-9 rounded-lg px-3 text-sm',
  md: 'h-10 rounded-xl px-4 text-sm',
  lg: 'h-11 rounded-xl px-5 text-sm',
  xl: 'h-12 rounded-xl px-6 text-sm',
};

const ACTION_AI_STYLES =
  'bg-[var(--home-action-ai-bg)] border border-[var(--home-action-ai-border)] text-[var(--home-action-ai-text)] hover:bg-[var(--home-action-ai-hover-bg)]';
const ACTION_REPORT_STYLES =
  'bg-[var(--home-action-report-bg)] border border-[var(--home-action-report-border)] text-[var(--home-action-report-text)] hover:bg-[var(--home-action-report-hover-bg)]';

const BUTTON_VARIANT_STYLES: Record<Variant, string> = {
  primary: 'border border-primary/20 bg-primary-gradient text-primary-foreground shadow-lg shadow-cyan/20 hover:-translate-y-0.5 hover:brightness-110 hover:shadow-cyan/22',
  secondary: 'border border-border/80 bg-card/90 text-foreground shadow-soft-card hover:-translate-y-0.5 hover:border-primary/25 hover:bg-muted/60',
  'settings-primary': 'border settings-button-primary hover:brightness-105 hover:shadow-xl',
  'settings-secondary': 'border settings-button-secondary hover:translate-y-[-1px]',
  outline: 'border border-primary/25 bg-transparent text-cyan hover:-translate-y-0.5 hover:bg-cyan/10',
  ghost: 'border border-transparent bg-transparent text-secondary-text hover:bg-hover hover:text-foreground',
  gradient: 'border border-primary/20 bg-gradient-to-r from-cyan to-accent-secondary text-primary-foreground shadow-lg shadow-cyan/20 hover:-translate-y-0.5 hover:brightness-110',
  danger: 'border border-danger/40 bg-danger text-destructive-foreground shadow-lg shadow-danger/20 hover:-translate-y-0.5 hover:brightness-105',
  'danger-subtle': 'border border-danger/60 bg-danger/10 text-danger hover:bg-danger/15',
  'action-primary': ACTION_AI_STYLES,
  'action-secondary': ACTION_REPORT_STYLES,
  'home-action-ai': ACTION_AI_STYLES,
  'home-action-report': ACTION_REPORT_STYLES,
};

const props = withDefaults(
  defineProps<{
    variant?: Variant;
    size?: Size;
    isLoading?: boolean;
    loadingText?: string;
    glow?: boolean;
    type?: 'button' | 'submit' | 'reset';
    disabled?: boolean;
  }>(),
  {
    variant: 'primary',
    size: 'md',
    isLoading: false,
    loadingText: '处理中...',
    glow: false,
    type: 'button',
    disabled: false,
  },
);

const btnClass = computed(() =>
  cn(
    'inline-flex cursor-pointer items-center justify-center gap-2 font-medium transition-all duration-200',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45 focus-visible:ring-offset-2 focus-visible:ring-offset-background',
    'active:scale-[0.98]',
    'disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 disabled:transform-none',
    BUTTON_SIZE_STYLES[props.size],
    BUTTON_VARIANT_STYLES[props.variant],
    props.glow ? 'shadow-glow-cyan settings-glow-cyan-hover' : '',
  ),
);
</script>

<template>
  <button
    :type="type"
    :aria-busy="isLoading || undefined"
    :data-variant="variant"
    :class="btnClass"
    :disabled="disabled || isLoading"
  >
    <span v-if="isLoading" class="flex items-center justify-center gap-2">
      <svg
        class="h-4 w-4 animate-spin text-current"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path
          class="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        />
      </svg>
      {{ loadingText }}
    </span>
    <slot v-else />
  </button>
</template>
