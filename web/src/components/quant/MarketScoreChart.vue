<script setup lang="ts">
import type { MarketRegime } from '@/types/quant';
import { computed } from 'vue';
import VChart from 'vue-echarts';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { useTheme } from '@/composables/useTheme';
import { useMediaQuery } from '@vueuse/core';
use([CanvasRenderer, LineChart, GridComponent, TooltipComponent]);
const props = defineProps<{ items: MarketRegime[] }>();
const { resolvedTheme } = useTheme();
const isMobile = useMediaQuery('(max-width: 639px)');
const option = computed(() => {
  const rows=[...props.items].reverse();
  const muted = resolvedTheme.value === 'dark' ? '#a9afbd' : '#667085';
  const split = resolvedTheme.value === 'dark' ? 'rgba(255,255,255,.1)' : 'rgba(15,23,42,.08)';
  return { tooltip:{trigger:'axis'}, grid:{left:isMobile.value ? 34 : 42,right:10,top:12,bottom:30}, xAxis:{type:'category',data:rows.map(i=>i.tradeDate),axisLabel:{hideOverlap:true,color:muted,fontSize:isMobile.value ? 10 : 12},axisLine:{lineStyle:{color:split}}}, yAxis:{type:'value',min:0,max:1,axisLabel:{color:muted},splitLine:{lineStyle:{color:split}}}, series:[{type:'line',smooth:true,showSymbol:false,data:rows.map(i=>i.marketScore),lineStyle:{color:'#df7997'},areaStyle:{color:'#df7997',opacity:.1}}] };
});
</script>
<template><VChart class="h-56 w-full" :option="option" autoresize /></template>
