<script setup lang="ts">
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

withDefaults(
  defineProps<{
    content?: unknown;
    side?: 'top' | 'right' | 'bottom' | 'left';
    focusable?: boolean;
    contentClass?: string;
  }>(),
  {
    content: undefined,
    side: 'top',
    focusable: false,
    contentClass: '',
  },
);
</script>
<template>
  <span
    v-if="!content"
    class="inline-flex"
  >
    <slot />
  </span>
  <TooltipProvider
    v-else
    :delay-duration="0"
  >
    <Tooltip>
      <TooltipTrigger as-child>
        <span
          class="inline-flex"
          :tabindex="focusable ? 0 : undefined"
        >
          <slot />
        </span>
      </TooltipTrigger>
      <TooltipContent
        :side="side"
        :class="contentClass"
      >
        {{ content }}
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
