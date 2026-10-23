<script setup lang="ts">
import { computed, ref } from 'vue';
import { useElementSize } from '@vueuse/core';
import type { HeatmapSnapshot, HeatmapStock } from '@/api/marketHeatmap';
import { changeColor, formatCap, formatChange, heatmapGroups } from './display';

const props = withDefaults(defineProps<{ snapshot: HeatmapSnapshot; search?: string; groupCode?: string }>(), {
  search: '', groupCode: '',
});
const emit = defineEmits<{ select: [stock: HeatmapStock] }>();
const container = ref<HTMLElement | null>(null);
const { width } = useElementSize(container);
const columns = computed(() => Math.max(1, Math.floor((width.value + 6) / 166)));
const groups = computed(() => heatmapGroups(props.snapshot.items, columns.value, props.search, props.groupCode));
</script>

<template>
  <div
    ref="container"
    class="min-w-0 space-y-7"
    aria-label="按行业分组的股票市值热力图"
    data-testid="heatmap-groups"
  >
    <section
      v-for="(group, index) in groups"
      :key="group.code"
      :aria-labelledby="`heatmap-group-${index}`"
      class="min-w-0 space-y-2"
      data-testid="heatmap-group"
    >
      <header class="flex items-baseline justify-between gap-3 border-b pb-2">
        <h3
          :id="`heatmap-group-${index}`"
          class="text-base font-semibold"
        >
          {{ group.name }}
        </h3>
        <span class="text-xs text-muted-foreground">{{ group.tiles.length }} 只股票</span>
      </header>
      <div
        class="heatmap-grid"
        :style="{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }"
      >
        <button
          v-for="tile in group.tiles"
          :key="tile.stock.code"
          type="button"
          class="heatmap-tile rounded-md text-white outline-none transition-[filter,box-shadow] hover:brightness-95 focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          :class="{ 'heatmap-tile-prominent': tile.prominent }"
          :style="{ backgroundColor: changeColor(tile.stock.changePct), gridColumn: `span ${tile.columnSpan}`, gridRow: `span ${tile.rowSpan}` }"
          :aria-label="`${tile.stock.name} ${tile.stock.code} ${formatChange(tile.stock.changePct)}，总市值 ${formatCap(tile.stock.marketCap, snapshot.market)}，查看详情`"
          :data-code="tile.stock.code"
          data-testid="heatmap-stock"
          @click="emit('select', tile.stock)"
        >
          <span
            class="heatmap-stock-name"
            data-testid="heatmap-stock-name"
          >{{ tile.stock.name }}</span>
          <span
            class="heatmap-stock-code"
            data-testid="heatmap-stock-code"
          >{{ tile.stock.code }}</span>
          <span
            class="heatmap-stock-change"
            data-testid="heatmap-stock-change"
          >{{ formatChange(tile.stock.changePct) }}</span>
          <span
            class="mt-1 shrink-0 text-[11px] leading-[15px]"
          >{{ formatCap(tile.stock.marketCap, snapshot.market) }}</span>
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.heatmap-grid {
  display: grid;
  grid-auto-flow: dense;
  grid-auto-rows: minmax(124px, auto);
  gap: 6px;
}
.heatmap-tile {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 10px;
  text-align: center;
}
.heatmap-stock-name {
  flex-shrink: 0;
  width: 100%;
  overflow-wrap: anywhere;
  font-size: 13px;
  font-weight: 600;
  line-height: 18px;
}
.heatmap-stock-code {
  flex-shrink: 0;
  margin-top: 4px;
  max-width: 100%;
  overflow-wrap: anywhere;
  font-size: 12px;
  line-height: 16px;
}
.heatmap-stock-change {
  flex-shrink: 0;
  margin-top: 3px;
  font-size: 18px;
  font-weight: 600;
  line-height: 24px;
  font-variant-numeric: tabular-nums;
}
.heatmap-tile-prominent .heatmap-stock-name {
  font-size: 16px;
  line-height: 22px;
}
.heatmap-tile-prominent .heatmap-stock-change {
  font-size: 24px;
  line-height: 30px;
}
</style>
