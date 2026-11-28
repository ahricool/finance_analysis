<script setup lang="ts">
import ChartPeriodSelector from './ChartPeriodSelector.vue';
import { provide, ref, watch } from 'vue';
import { Button } from '@/components/ui/button';
import { Table } from '@/components/ui/table';
import { createExpansion, expansionKey, tableChartPeriod } from './state';

defineOptions({ inheritAttrs: false });
const props = withDefaults(defineProps<{ charts?: boolean; expansion?: ReturnType<typeof createExpansion> }>(), { charts: true, expansion: undefined });
const emit = defineEmits<{ viewport: [element: HTMLElement | null] }>();
const table = ref<InstanceType<typeof Table> | null>(null);
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
  >
    <slot />
  </Table>
</template>
