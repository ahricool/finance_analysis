<script setup lang="ts">
import type { HTMLAttributes } from 'vue';
import { Dialog, DialogDescription, DialogHeader, DialogScrollContent, DialogTitle } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
const props = withDefaults(defineProps<{
  open: boolean;
  title: string;
  description?: string;
  eyebrow?: string;
  contentClass?: HTMLAttributes['class'];
  class?: HTMLAttributes['class'];
}>(), { description: '', eyebrow: '' });
const emit = defineEmits<{ 'update:open': [value: boolean] }>();
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogScrollContent :class="cn('max-h-[calc(100dvh-1rem)] w-[calc(100%-1rem)] max-w-2xl gap-0 overflow-hidden rounded-2xl p-0 sm:max-h-[calc(100dvh-3rem)]', props.class)">
      <DialogHeader class="border-b p-5 pr-14 text-left">
        <p v-if="eyebrow" class="text-xs font-medium uppercase tracking-wider text-primary">{{ eyebrow }}</p>
        <DialogTitle>{{ title }}</DialogTitle>
        <DialogDescription v-if="description">{{ description }}</DialogDescription>
      </DialogHeader>
      <div :class="cn('min-h-0 overflow-y-auto p-5', contentClass)"><slot /></div>
    </DialogScrollContent>
  </Dialog>
</template>
