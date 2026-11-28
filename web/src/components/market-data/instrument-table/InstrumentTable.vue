<script setup lang="ts">
import ChartPeriodSelector from './ChartPeriodSelector.vue';
import { computed, provide, ref, watch } from 'vue';
import { useElementSize } from '@vueuse/core';
import { Button } from '@/components/ui/button';
import { Table } from '@/components/ui/table';
import { createExpansion, expansionKey, tableChartPeriod } from './state';

defineOptions({ inheritAttrs: false });
const props = withDefaults(defineProps<{ freezeFavorite?: boolean; charts?: boolean; expansion?: ReturnType<typeof createExpansion> }>(), { charts: true, expansion: undefined });
const emit = defineEmits<{ viewport: [element: HTMLElement | null] }>();
const table = ref<InstanceType<typeof Table> | null>(null);
const favoriteHead = computed(() => props.freezeFavorite
  ? table.value?.$el.querySelector('thead th:first-child') as HTMLElement | null : null);
const { width: favoriteWidth } = useElementSize(favoriteHead, undefined, { box: 'border-box' });
watch(table, (value, _, cleanup) => {
  if (value) emit('viewport', value.$el);
  cleanup(() => emit('viewport', null));
});
const expansion = props.expansion ?? createExpansion();
provide(expansionKey, expansion);
</script>

<template>
  <div
    v-if="charts"
    class="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/25 px-3 py-2"
    aria-label="表格 K 线"
    role="toolbar"
  >
    <div class="flex gap-1">
      <Button
        size="sm"
        variant="outline"
        @click="expansion.setAll(true)"
      >
        全部展开
      </Button>
      <Button
        size="sm"
        variant="outline"
        @click="expansion.setAll(false)"
      >
        全部收起
      </Button>
    </div>
    <ChartPeriodSelector v-model="tableChartPeriod" />
  </div>
  <Table
    ref="table"
    v-bind="$attrs"
    :class="{ 'freeze-favorite': freezeFavorite }"
    :style="freezeFavorite ? { '--favorite-width': favoriteWidth + 'px' } : undefined"
  >
    <slot />
  </Table>
</template>
