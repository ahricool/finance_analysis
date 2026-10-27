<script setup lang="ts">
import type { RealtimeConnectionStatus } from '@/api/realtimeMarket';
import { computed } from 'vue';

const props = defineProps<{ status: RealtimeConnectionStatus }>();
const label = computed(() => {
  if (props.status === 'connected') return '实时行情';
  if (props.status === 'sse') return '行情已连接 · SSE';
  if (props.status === 'sse-reconnecting') return '备用行情连接中 · SSE';
  if (props.status === 'unauthorized') return '行情未授权';
  if (props.status === 'reconnecting') return '行情重连中';
  if (props.status === 'paused') return '页面在后台，行情已暂停';
  return '行情连接中';
});
</script>

<template>
  <span class="inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-muted-foreground">
    <span
      class="h-1.5 w-1.5 rounded-full"
      :class="
        status === 'connected' || status === 'sse'
          ? 'bg-success'
          : status === 'unauthorized'
            ? 'bg-destructive'
            : status === 'paused'
              ? 'bg-muted-foreground'
              : 'animate-pulse bg-warning'
      "
    />
    {{ label }}
  </span>
</template>
