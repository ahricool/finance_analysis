<script setup lang="ts">
import { ref, watch } from 'vue';
import { stocksApi, type StockIndexMembership } from '@/api/stocks';
import { Badge } from '@/components/ui/badge';

const props = defineProps<{ code: string }>();
const indices = ref<StockIndexMembership[]>([]);

watch(() => props.code, async (code, _previous, onCleanup) => {
  const controller = new AbortController();
  onCleanup(() => controller.abort());
  indices.value = [];
  if (!code) return;
  try {
    const result = await stocksApi.classification(code, controller.signal);
    if (!controller.signal.aborted) indices.value = result.memberships.indices;
  } catch {
    // Optional metadata must not interrupt quotes or charts.
  }
}, { immediate: true });
</script>

<template>
  <div
    v-if="indices.length"
    class="flex flex-wrap items-center gap-1.5"
    aria-label="当前所属指数"
    data-testid="stock-membership-tags"
  >
    <Badge
      v-for="index in indices"
      :key="index.key"
      variant="secondary"
    >
      {{ index.name }}
    </Badge>
  </div>
</template>
