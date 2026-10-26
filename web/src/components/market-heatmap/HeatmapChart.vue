<script setup lang="ts">
import { computed, ref } from 'vue';
import { useElementSize } from '@vueuse/core';
import type { HeatmapSnapshot, HeatmapStock } from '@/api/marketHeatmap';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { vFitLabel } from './fitLabel';
import { changeColor, formatCap, formatChange, heatmapGroups } from './display';

const props = withDefaults(defineProps<{ snapshot: HeatmapSnapshot; search?: string; groupCode?: string }>(), {
  search: '', groupCode: '',
});
const emit = defineEmits<{ select: [stock: HeatmapStock] }>();
const container = ref<HTMLElement | null>(null);
const { width } = useElementSize(container);
const columns = computed(() => width.value >= 1000 && !props.groupCode ? 2 : 1);
const panelWidth = computed(() => Math.max(240, (width.value - (columns.value - 1) * 20) / columns.value));
const groups = computed(() => heatmapGroups(props.snapshot.items, panelWidth.value, props.search, props.groupCode));
</script>

<template>
  <TooltipProvider :delay-duration="150">
    <div
      ref="container"
      class="heatmap-groups"
      :style="{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }"
      aria-label="按行业分组的股票市值热力图"
      data-testid="heatmap-groups"
    >
      <section
        v-for="(group, index) in groups"
        :key="group.code"
        :aria-labelledby="`heatmap-group-${index}`"
        class="min-w-0"
        data-testid="heatmap-group"
      >
        <header class="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <h3
            :id="`heatmap-group-${index}`"
            class="text-sm font-semibold"
          >
            {{ group.name }}
          </h3>
          <span class="text-[11px] text-muted-foreground">{{ group.totalCount }} 只股票</span>
        </header>
        <div
          class="heatmap-map"
          :style="{ height: `${group.height}px` }"
        >
          <Tooltip
            v-for="tile in group.tiles"
            :key="tile.stock.code"
          >
            <TooltipTrigger as-child>
              <button
                v-fit-label
                type="button"
                class="heatmap-tile text-white outline-none hover:brightness-110 focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-foreground"
                :style="{ backgroundColor: changeColor(tile.stock.changePct), left: `${tile.x / panelWidth * 100}%`, top: `${tile.y}px`, width: `${tile.width / panelWidth * 100}%`, height: `${tile.height}px` }"
                :aria-label="`${tile.stock.name} ${tile.stock.code} ${formatChange(tile.stock.changePct)}，总市值 ${formatCap(tile.stock.marketCap, snapshot.market)}，查看详情`"
                :data-code="tile.stock.code"
                data-testid="heatmap-stock"
                @click="emit('select', tile.stock)"
              >
                <span class="heatmap-labels">
                  <span
                    class="heatmap-stock-name"
                    data-testid="heatmap-stock-name"
                  >{{ snapshot.market === 'US' ? tile.stock.code.replace(/\.US$/, '') : (tile.stock.name?.trim() || tile.stock.code) }}</span>
                  <span
                    class="heatmap-stock-change"
                    data-testid="heatmap-stock-change"
                  >{{ tile.stock.changePct === null ? '—' : formatChange(tile.stock.changePct) }}</span>
                </span>
              </button>
            </TooltipTrigger>
            <TooltipContent class="flex-col items-start">
              <p class="font-semibold">
                {{ tile.stock.name }} · {{ tile.stock.code }}
              </p>
              <p>{{ formatChange(tile.stock.changePct) }} · 总市值 {{ formatCap(tile.stock.marketCap, snapshot.market) }}</p>
            </TooltipContent>
          </Tooltip>
        </div>
      </section>
    </div>
  </TooltipProvider>
</template>

<style scoped>
.heatmap-groups {
  display: grid;
  gap: 24px 20px;
  align-items: start;
  min-width: 0;
}
.heatmap-map { position: relative; }
.heatmap-tile {
  position: absolute;
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 1px;
  overflow: hidden;
  border: 1px solid hsl(var(--background));
  text-align: center;
}
.heatmap-labels {
  display: flex;
  flex-direction: column;
  gap: 1px;
  width: 100%;
  min-width: 0;
  visibility: hidden;
  white-space: nowrap;
  font-size: var(--heatmap-font-size, 16px);
  font-weight: 600;
  line-height: 1.15;
}
.heatmap-stock-change {
  font-variant-numeric: tabular-nums;
}
</style>
