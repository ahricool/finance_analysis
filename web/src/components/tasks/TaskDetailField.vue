<script setup lang="ts">
withDefaults(
  defineProps<{
    label: string;
    mono?: boolean;
  }>(),
  { mono: false },
);
</script>

<template>
  <div class="min-w-0">
    <dt class="text-xs text-muted-foreground">
      {{ label }}
    </dt>
    <dd
      :class="[
        'mt-1 break-words text-foreground',
        mono ? 'font-mono text-xs leading-relaxed' : 'text-sm',
      ]"
    >
      <slot />
    </dd>
  </div>
</template>
