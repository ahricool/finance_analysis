<script setup lang="ts">
import type { ParsedApiError } from '@/api/error';
import { Skeleton } from '@/components/ui/skeleton';
withDefaults(defineProps<{
  state: { loading: boolean; error: ParsedApiError | null };
  empty?: boolean;
  emptyMessage?: string;
}>(), {
  empty: false,
  emptyMessage: '暂无已发布数据（非交易日或尚未生成）',
});
defineEmits<{ retry: [] }>();
</script>

<template>
  <div
    v-if="state.loading"
    class="space-y-3 py-5"
    aria-label="正在加载"
  >
    <Skeleton class="h-5 w-2/3" /><Skeleton class="h-12 w-full" /><Skeleton class="h-4 w-1/2" />
  </div>
  <div
    v-else-if="state.error"
    class="flex items-center justify-between gap-3 py-6 text-sm"
    role="status"
  >
    <span class="text-muted-foreground">请求失败 · {{ state.error.title }}</span>
    <button
      class="shrink-0 underline underline-offset-4"
      @click="$emit('retry')"
    >
      重试
    </button>
  </div>
  <p
    v-else-if="empty"
    class="py-6 text-sm text-muted-foreground"
  >
    {{ emptyMessage }}
  </p>
  <slot v-else />
</template>
