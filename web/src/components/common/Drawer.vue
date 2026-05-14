<script setup lang="ts">
import { watchEffect, useId } from 'vue';
import { cn } from '@/utils/cn';

const props = withDefaults(
  defineProps<{
    isOpen: boolean;
    title?: string;
    width?: string;
    zIndex?: number;
    side?: 'left' | 'right';
    backdropClassName?: string;
  }>(),
  {
    width: 'max-w-2xl',
    zIndex: 50,
    side: 'right',
  },
);

const emit = defineEmits<{
  close: [];
}>();

let activeDrawerCount = 0;

const uid = useId();
const titleId = `drawer-title-${props.side}-${uid}`;

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    emit('close');
  }
}

watchEffect((onCleanup) => {
  if (!props.isOpen) return;

  document.addEventListener('keydown', handleKeyDown);
  activeDrawerCount++;
  if (activeDrawerCount === 1) {
    document.body.style.overflow = 'hidden';
  }

  onCleanup(() => {
    document.removeEventListener('keydown', handleKeyDown);
    activeDrawerCount--;
    if (activeDrawerCount === 0) {
      document.body.style.overflow = '';
    }
  });
});

</script>

<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="fixed inset-0 overflow-hidden"
      role="presentation"
      :style="{ zIndex: zIndex }"
    >
      <div
        :class="
          cn(
            'absolute inset-0 bg-background/80 backdrop-blur-sm transition-opacity duration-300',
            backdropClassName,
          )
        "
        @click="emit('close')"
      />

      <div :class="cn('absolute inset-y-0 flex w-full', side === 'left' ? 'left-0 justify-start' : 'right-0 justify-end', width)">
        <div
          role="dialog"
          aria-modal="true"
          :aria-labelledby="title ? titleId : undefined"
          :class="
            cn(
              'relative flex w-full flex-col bg-card',
              side === 'left' ? 'border-r' : 'border-l',
              side === 'right' ? 'border-border/80' : 'border-border/70 shadow-2xl',
              side === 'left' ? 'animate-slide-in-left' : 'animate-slide-in-right',
            )
          "
        >
          <div class="flex items-center justify-between border-b border-border/60 px-6 py-4">
            <div v-if="title">
              <span class="label-uppercase">DETAIL VIEW</span>
              <h2 :id="titleId" class="mt-1 text-lg font-semibold text-foreground">
                {{ title }}
              </h2>
            </div>
            <div v-else />
            <button
              type="button"
              class="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border/70 bg-card/80 text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
              aria-label="关闭抽屉"
              @click="emit('close')"
            >
              <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div class="flex-1 overflow-y-auto p-6">
            <slot />
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
