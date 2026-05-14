<script setup lang="ts">
import { cn } from '@/utils/cn';
import { ref } from 'vue';

const props = withDefaults(
  defineProps<{
    title: string;
    defaultOpen?: boolean;
    class?: string;
  }>(),
  {
    defaultOpen: false,
    class: '',
  },
);

const isOpen = ref(props.defaultOpen);
</script>

<template>
  <div
    :class="
      cn(
        'overflow-hidden rounded-2xl border border-subtle bg-card/70 shadow-soft-card transition-all duration-300',
        'hover:border-accent',
        props.class,
      )
    "
  >
    <button
      type="button"
      class="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-hover"
      @click="isOpen = !isOpen"
    >
      <div class="flex items-center gap-3">
        <span v-if="$slots.icon" class="text-cyan">
          <slot name="icon" />
        </span>
        <span class="font-medium text-foreground">{{ title }}</span>
      </div>
      <svg
        :class="
          cn('h-5 w-5 text-secondary-text transition-transform duration-300', isOpen && 'rotate-180')
        "
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
      </svg>
    </button>

    <div
      :class="
        cn(
          'overflow-hidden transition-all duration-300 ease-in-out',
          isOpen ? 'max-h-[2000px] opacity-100' : 'max-h-0 opacity-0',
        )
      "
    >
      <div class="border-t border-subtle px-4 pb-4 pt-2">
        <slot />
      </div>
    </div>
  </div>
</template>
