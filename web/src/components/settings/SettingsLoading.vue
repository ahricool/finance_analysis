<script setup lang="ts">
const placeholders = Array.from({ length: 6 }, (_, i) => i);
</script>

<template>
  <div class="space-y-4 animate-fade-in">
    <div
      v-for="n in placeholders"
      :key="n"
      class="rounded-[1.15rem] border settings-border bg-[var(--settings-surface)] p-4 shadow-soft-card"
    >
      <div class="settings-skeleton-strong h-3 w-32 rounded" />
      <div class="settings-skeleton-soft mt-3 h-10 rounded-lg" />
    </div>
  </div>
</template>
