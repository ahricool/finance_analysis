<script setup lang="ts">
import { Card } from '@/components/ui/card';

withDefaults(
  defineProps<{
    title: string;
    description?: string;
    class?: string;
  }>(),
  { description: '', class: '' },
);
</script>
<template>
  <Card :class="['border-dashed p-8 text-center', $props.class]">
    <div
      v-if="$slots.icon"
      class="mb-4 flex justify-center text-primary"
    >
      <slot name="icon" />
    </div>
    <h3 class="font-semibold">
      {{ title }}
    </h3>
    <p
      v-if="description"
      class="mx-auto mt-2 max-w-md text-sm text-muted-foreground"
    >
      {{ description }}
    </p>
    <div
      v-if="$slots.action"
      class="mt-5 flex justify-center"
    >
      <slot name="action" />
    </div>
  </Card>
</template>
