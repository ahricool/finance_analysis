<script setup lang="ts">
import type { HTMLAttributes } from 'vue';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { cn } from '@/lib/utils';

const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    description?: string;
    side?: 'top' | 'right' | 'bottom' | 'left';
    class?: HTMLAttributes['class'];
  }>(),
  {
    description: '',
    side: 'right',
    class: '',
  },
);
const emit = defineEmits<{ 'update:open': [value: boolean] }>();
</script>

<template>
  <Sheet
    :open="open"
    @update:open="emit('update:open', $event)"
  >
    <SheetContent
      :side="side"
      :class="cn('flex max-h-dvh w-full flex-col overflow-hidden sm:max-w-xl', props.class)"
    >
      <SheetHeader class="shrink-0 text-left">
        <SheetTitle>{{ title }}</SheetTitle>
        <SheetDescription v-if="description">
          {{ description }}
        </SheetDescription>
      </SheetHeader>
      <div class="min-h-0 flex-1 overflow-y-auto pb-[max(1rem,env(safe-area-inset-bottom))]">
        <slot />
      </div>
    </SheetContent>
  </Sheet>
</template>
