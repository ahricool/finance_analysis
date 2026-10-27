<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import HeatmapChart from '@/components/market-heatmap/HeatmapChart.vue';
import { colorScale, formatCap, formatChange } from '@/components/market-heatmap/display';
import type { HeatmapMarket, HeatmapStock } from '@/api/marketHeatmap';
import { demoSnapshot } from './heatmap-demo-data';
const market = ref<HeatmapMarket>('US');
const search = ref('');
const group = ref('');
const dark = ref(false);
const selected = ref<HeatmapStock | null>(null);
const snapshot = computed(() => demoSnapshot(market.value));
const groups = computed(() => [...new Map(snapshot.value.items.map(s => [s.groupCode, s.groupName]))]);
watch(dark, value => document.documentElement.classList.toggle('dark', value));
watch(market, () => { search.value = ''; group.value = ''; selected.value = null; });
</script>
<template>
  <main class="mx-auto max-w-[1440px] space-y-5 px-5 py-8 text-foreground sm:px-10">
    <header class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold">
          热力图
        </h1><p class="mt-1 text-sm text-muted-foreground">
          Demo review · 全部为模拟数据，仅用于布局评审
        </p>
      </div>
      <div class="flex gap-2">
        <button
          v-for="value in (['CN', 'US'] as const)"
          :key="value"
          class="rounded border px-4 py-2 text-sm"
          :class="market === value ? 'bg-foreground text-background' : ''"
          @click="market = value"
        >
          {{ value === 'CN' ? 'A 股' : '美股' }}
        </button>
        <button
          class="rounded border px-4 py-2 text-sm"
          @click="dark = !dark"
        >
          {{ dark ? '浅色' : '深色' }}
        </button>
      </div>
    </header>
    <div class="sticky top-0 z-20 flex flex-wrap gap-3 bg-background py-3">
      <input
        v-model="search"
        aria-label="搜索股票"
        placeholder="搜索名称或代码"
        class="min-w-0 flex-1 rounded border bg-background px-3 py-2 text-sm"
      >
      <select
        v-model="group"
        aria-label="行业"
        class="rounded border bg-background px-3 py-2 text-sm"
      >
        <option value="">
          全部行业
        </option><option
          v-for="[code, name] in groups"
          :key="code"
          :value="code"
        >
          {{ name }}
        </option>
      </select>
    </div>
    <div class="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
      <div class="flex">
        <span
          v-for="step in colorScale"
          :key="step.label"
          class="px-2 py-1 text-white"
          :style="{ background: step.color }"
        >{{ step.label }}</span>
      </div>
      <p>全部股票 · 小方块悬浮查看 · 向下浏览</p>
    </div>
    <HeatmapChart
      :snapshot="snapshot"
      :search="search"
      :group-code="group"
      @select="selected = $event"
    />
    <p
      v-if="selected"
      class="fixed inset-x-5 bottom-4 z-30 rounded-lg border bg-background p-4 shadow-lg"
      role="status"
      @click="selected = null"
    >
      {{ selected.name }} · {{ selected.code }} · {{ formatChange(selected.changePct) }} · {{ formatCap(selected.marketCap, market) }}（模拟数据，点击关闭）
    </p>
  </main>
</template>
