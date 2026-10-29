<script setup lang="ts">
import ConfluenceEvidence from '@/components/confluence/ConfluenceEvidence.vue';
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import type { StockDetailPanelProps } from './types';
import { confluenceApi as api, type ConfluenceItem } from '@/api/confluence';
const props = defineProps<StockDetailPanelProps>();
const selected = shallowRef<ConfluenceItem | null>(null);
const result = shallowRef<{ tradeDate: string; algorithmVersion: string } | null>(null);
const loading = ref(false);
const error = shallowRef<ParsedApiError | null>(null);
const supported = computed(() => props.market === 'CN' || props.market === 'US');
let generation = 0;
async function load() {
  const token = ++generation;
  selected.value = null; result.value = null; error.value = null; loading.value = false;
  if (props.market !== 'CN' && props.market !== 'US') return;
  const market = props.market, symbol = props.symbol, requestedDate = props.context?.tradeDate;
  loading.value = true;
  try {
    const date = requestedDate || (await api.dates(market)).slice().sort().at(-1);
    if (token !== generation || !date) return;
    const response = await api.detail(symbol, market, date);
    if (token === generation) { result.value = response; selected.value = response.item; }
  } catch (cause) {
    if (token === generation) { const parsed = getParsedApiError(cause); if (parsed.status !== 404) error.value = parsed; }
  } finally { if (token === generation) loading.value = false; }
}
watch([() => props.symbol, () => props.market, () => props.context?.tradeDate], load, { immediate: true });
onBeforeUnmount(() => { ++generation; });
</script>
<template>
  <div
    class="space-y-5"
    data-testid="confluence-detail-panel"
  >
    <p class="text-xs text-muted-foreground">
      正式共振快照 · {{ result?.tradeDate || context?.tradeDate || '最新日期' }} · {{ result?.algorithmVersion }} · 各来源以独立日期为准
    </p>
    <p
      v-if="loading"
      role="status"
    >
      正在读取共振证据…
    </p>
    <AppApiErrorAlert
      v-else-if="error"
      :error="error"
      action-label="重试"
      @action="load"
    />
    <p
      v-else-if="!selected"
      class="text-sm text-muted-foreground"
    >
      {{ supported ? '该股票在所选日期暂无正式共振信号。' : '此市场暂不支持共振研究。' }}
    </p>
    <template v-if="selected">
      <div class="flex flex-wrap items-end justify-between gap-4 rounded-xl border bg-muted/25 p-5">
        <div>
          <p class="text-xs text-muted-foreground">
            综合共振分
          </p><p class="mt-1 text-4xl font-semibold tracking-tight tabular-nums">
            {{ selected.confluenceScore?.toFixed(1) ?? '—' }}<span class="ml-1 text-sm font-normal text-muted-foreground">/100</span>
          </p>
        </div><div class="text-right text-xs text-muted-foreground">
          <p>{{ selected.positiveSignalCount }} 个正向 · {{ selected.availableSignalCount }} 个有效维度</p><p class="mt-1">
            缺失不参与分母 · 可用基础权重 {{ selected.availableWeight }}/100
          </p>
        </div>
      </div>
      <ConfluenceEvidence :row="selected" />
      <section class="border-t pt-4">
        <h3 class="mb-2 text-sm font-semibold">
          Why Confluence
        </h3><p
          v-for="reason in selected.reasons"
          :key="reason"
          class="text-xs text-muted-foreground"
        >
          {{ reason }}
        </p>
      </section>
    </template>
  </div>
</template>
