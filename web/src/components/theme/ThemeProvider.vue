<script setup lang="ts">
import { onMounted } from 'vue';
import { initThemeRuntime } from '@/composables/useTheme';

onMounted(() => {
  initThemeRuntime();
});
</script>

<template>
  <slot />
</template>
