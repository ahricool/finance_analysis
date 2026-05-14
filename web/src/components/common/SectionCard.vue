<script setup lang="ts">
import Card from '@/components/common/Card.vue';

defineProps<{
  title: string;
  subtitle?: string;
  class?: string;
}>();
</script>

<template>
  <Card :class="$props.class" padding="md" variant="bordered">
    <div class="mb-4 flex items-start justify-between gap-3">
      <div>
        <span v-if="subtitle" class="label-uppercase">{{ subtitle }}</span>
        <h2 class="mt-1 text-lg font-semibold text-foreground">{{ title }}</h2>
      </div>
      <div v-if="$slots.actions" class="flex shrink-0 items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
    <slot />
  </Card>
</template>
