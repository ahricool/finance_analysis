<script setup lang="ts">
import type { RealtimeConnectionStatus } from '@/api/realtimeMarket';
import { computed } from 'vue';

const props = defineProps<{ status: RealtimeConnectionStatus }>();
const label = computed(() => {
  if (props.status === 'connected') return '实时行情';
  if (props.status === 'unauthorized') return '行情未授权';
  if (props.status === 'reconnecting') return '行情重连中';
  return '行情连接中';
});
</script>

<template>
  <span class="inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-muted-text">
    <span
      class="h-1.5 w-1.5 rounded-full"
      :class="status === 'connected' ? 'bg-emerald-500' : status === 'unauthorized' ? 'bg-destructive' : 'animate-pulse bg-amber-500'"
    />
    {{ label }}
  </span>
</template>
