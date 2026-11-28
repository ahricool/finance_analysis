<script setup lang="ts">
import { nextTick, ref } from 'vue';
import { ArrowUpRight } from 'lucide-vue-next';
import type { ContractQuote } from '@/api/contracts';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useStockDetail } from '@/composables/useStockDetail';
import MinuteForecastSwitch from '@/components/stocks/detail/MinuteForecastSwitch.vue';
import ChartPeriodSelector from '@/components/market-data/instrument-table/ChartPeriodSelector.vue';
import type { ChartPeriod } from '@/components/market-data/instrument-table/state';
import { signedTextClass } from '@/utils/marketTone';
import { anchorMarket } from './anchorMarket';
import ContractRowChart from './ContractRowChart.vue';

const props = defineProps<{ row: ContractQuote }>();
const emit = defineEmits<{ close: [] }>();
const detail = useStockDetail();
const period = ref<ChartPeriod>('1m');
async function openAnchor() {
  const code = props.row.underlying_symbol;
  if (!code) return;
  emit('close');
  await nextTick();
  detail.open({ code, marketType: anchorMarket(code), name: null });
}
</script>
<template>
  <Dialog
    open
    @update:open="open => { if (!open) emit('close'); }"
  >
    <DialogContent class="max-h-[90dvh] overflow-y-auto sm:max-w-5xl">
      <DialogHeader>
        <DialogDescription>Binance · USDT 本位永续</DialogDescription>
        <DialogTitle class="text-2xl">
          {{ row.symbol }}
        </DialogTitle>
      </DialogHeader>
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-baseline gap-2 tabular-nums">
          <strong class="text-2xl">{{ row.quote?.price.toLocaleString('en-US', { maximumFractionDigits: 10 }) ?? '—' }}</strong>
          <span class="text-xs text-muted-foreground">USDT</span>
          <span
            v-if="row.quote"
            :class="signedTextClass(row.quote.change_pct)"
          >{{ row.quote.change_pct.toFixed(2) }}%</span>
        </div>
        <Button
          v-if="row.underlying_symbol"
          variant="outline"
          size="sm"
          @click="openAnchor"
        >
          锚定标的 {{ row.underlying_symbol }} <ArrowUpRight />
        </Button>
      </div>
      <MinuteForecastSwitch
        :symbol="row.symbol"
        contract
      />
      <ChartPeriodSelector v-model="period" />
      <ContractRowChart
        :row="row"
        :period="period"
      />
    </DialogContent>
  </Dialog>
</template>
