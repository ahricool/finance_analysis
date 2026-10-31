<script setup lang="ts">
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { holdingsApi, type PortfolioAccount, type PortfolioPosition } from '@/api/holdings';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import DailyKLineCard from '@/components/market-data/DailyKLineCard.vue';
import { Button } from '@/components/ui/button';
import type { TradeMarker } from '@/lib/tradeMarkers';
import type { StockDetailPanelProps } from './types';

const props = defineProps<StockDetailPanelProps>();
const positions = ref<PortfolioPosition[]>([]);
const accounts = ref<PortfolioAccount[]>([]);
const selectedId = ref<number | null>(null);
const detail = computed(() => positions.value.find(row => row.id === selectedId.value) ?? null);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const detailLoading = ref(false);
const detailError = ref<ParsedApiError | null>(null);
const operations = ref<Array<{ executedAt: string; side: string; quantity: string; price: string }>>([]);
const markers = ref<TradeMarker[]>([]);
let request = 0, detailRequest = 0;
let stopped = false;
const supported = computed(() => props.market === 'CN' || props.market === 'US');
function fmt(value?: string | null) {
  if (value == null || value === '') return '—';
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString(undefined, { maximumFractionDigits: 4 }) : value;
}
function accountName(accountId: number) {
  return accounts.value.find(row => row.id === accountId)?.name ?? `账户 ${accountId}`;
}
async function load() {
  const current = ++request;
  detailRequest++;
  positions.value = []; accounts.value = []; selectedId.value = null;
  operations.value = []; markers.value = [];
  error.value = null; detailError.value = null;
  detailLoading.value = false; loading.value = false;
  if (!supported.value) return;
  loading.value = true;
  try {
    const summary = await holdingsApi.summary(props.market);
    if (stopped || current !== request) return;
    accounts.value = summary.accounts;
    positions.value = summary.positions.filter(row => row.symbol === props.symbol
      && (props.context?.accountId == null || row.accountId === props.context.accountId));
    selectedId.value = props.context?.positionId != null
      ? positions.value.find(row => row.id === props.context?.positionId)?.id ?? null
      : positions.value[0]?.id ?? null;
  } catch (err) {
    if (!stopped && current === request) error.value = getParsedApiError(err);
  } finally {
    if (!stopped && current === request) loading.value = false;
  }
}
async function loadOperations() {
  const current = ++detailRequest;
  const row = detail.value;
  operations.value = []; markers.value = []; detailError.value = null; detailLoading.value = false;
  if (!row) return;
  detailLoading.value = true;
  try {
    const [ops, marks] = await Promise.all([holdingsApi.operations(row.id), holdingsApi.markers(row.id)]);
    if (stopped || current !== detailRequest || detail.value?.id !== row.id) return;
    operations.value = ops;
    markers.value = marks.map(item => ({ timestamp: Date.parse(item.timestamp), type: item.type, operations: item.operations }));
  } catch (err) {
    if (!stopped && current === detailRequest) detailError.value = getParsedApiError(err);
  } finally {
    if (!stopped && current === detailRequest) detailLoading.value = false;
  }
}
watch([() => props.symbol, () => props.market, () => props.context?.accountId, () => props.context?.positionId], load, { immediate: true });
watch(() => detail.value?.id, loadOperations);
onBeforeUnmount(() => { stopped = true; request++; detailRequest++; });
</script>

<template>
  <div
    class="space-y-4"
    data-testid="holdings-detail-panel"
  >
    <p class="text-sm text-muted-foreground">
      当前实际持仓与账户记录，不随研究快照日期回溯。
    </p>
    <p
      v-if="!supported"
      class="text-sm text-muted-foreground"
    >
      该市场暂不支持持仓管理。
    </p>
    <p
      v-else-if="loading"
      role="status"
      class="text-sm text-muted-foreground"
    >
      正在加载持仓…
    </p>
    <ApiErrorAlert
      v-else-if="error"
      :error="error"
      action-label="重试持仓"
      @action="load"
    />
    <p
      v-else-if="!detail"
      class="text-sm text-muted-foreground"
    >
      当前账户暂无该证券持仓。
    </p>
    <template v-else>
      <label
        v-if="positions.length > 1"
        class="flex flex-wrap items-center gap-2 text-sm"
      >
        持仓账户
        <FieldSelect
          :model-value="String(selectedId ?? '')"
          :options="positions.map(row => ({ value: String(row.id), label: accountName(row.accountId) }))"
          aria-label="持仓账户"
          class="w-full sm:w-56"
          data-testid="holding-account"
          @update:model-value="selectedId = Number($event)"
        />
      </label>
      <p
        v-else
        class="text-sm text-muted-foreground"
      >
        {{ accountName(detail.accountId) }}
      </p>
      <p>数量 {{ fmt(detail.quantity) }} · 成本 {{ fmt(detail.averageCost) }} · 市值 {{ fmt(detail.marketValue) }}</p>
      <ApiErrorAlert
        v-if="detailError"
        :error="detailError"
      />
      <Button
        v-if="detailError"
        variant="outline"
        @click="loadOperations"
      >
        重试详情
      </Button>
      <DailyKLineCard
        :key="detail.id"
        :symbol="detail.symbol"
        :markers="markers"
        marker-caption="操作 BST"
      />
      <div>
        <h3 class="mb-2 text-sm font-semibold">
          操作记录
        </h3>
        <p
          v-if="detailLoading"
          class="text-sm text-muted-foreground"
        >
          正在加载操作记录…
        </p>
        <p
          v-else-if="!detailError && !operations.length"
          class="text-sm text-muted-foreground"
        >
          暂无操作记录
        </p>
        <p
          v-for="item in operations"
          :key="item.executedAt + item.side"
        >
          {{ item.executedAt }} {{ item.side }} {{ item.quantity }} @{{ item.price }}
        </p>
      </div>
    </template>
  </div>
</template>
