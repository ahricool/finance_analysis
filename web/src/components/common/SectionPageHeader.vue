<script setup lang="ts">
defineProps<{
  title: string;
  description: string;
}>();
</script>

<template>
  <header class="flex flex-col gap-1 font-sans">
    <h1 class="text-xl font-semibold text-foreground">
      {{ title }}
    </h1>
    <p class="text-sm text-muted-text">
      {{ description }}
    </p>
    <slot />
  </header>
</template>
