<script setup lang="ts">
import { sessionStyles } from './tradingSessionOverlay';
</script>
<template>
  <div
    class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground"
    aria-label="交易时段图例"
  >
    <span
      v-for="(style, key) in sessionStyles"
      :key="key"
      class="inline-flex items-center gap-1.5"
    >
      <span
        class="inline-block h-2 w-3 rounded-sm"
        :style="{ backgroundColor: style.color }"
      />{{ style.label }}
    </span>
  </div>
</template>
