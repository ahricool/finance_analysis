<script setup lang="ts">
defineProps<{ class?: string }>();
</script>
<template>
  <div :class="['mx-auto w-full max-w-7xl space-y-6 py-4 sm:py-6', $props.class]">
    <slot />
  </div>
</template>
