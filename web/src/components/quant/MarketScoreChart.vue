<script setup lang="ts">
import type { MarketRegime } from '@/types/quant';
import { computed } from 'vue';
import VChart from 'vue-echarts';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
use([CanvasRenderer, LineChart, GridComponent, TooltipComponent]);
const props = defineProps<{ items: MarketRegime[] }>();
const option = computed(() => {
  const rows=[...props.items].reverse();
  return { tooltip:{trigger:'axis'}, grid:{left:36,right:12,top:12,bottom:28}, xAxis:{type:'category',data:rows.map(i=>i.tradeDate),axisLabel:{hideOverlap:true}}, yAxis:{type:'value',min:0,max:1}, series:[{type:'line',smooth:true,showSymbol:false,data:rows.map(i=>i.marketScore),areaStyle:{opacity:.08}}] };
});
</script>
<template><VChart class="h-56 w-full" :option="option" autoresize /></template>
