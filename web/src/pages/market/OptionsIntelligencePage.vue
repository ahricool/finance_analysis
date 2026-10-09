<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { optionsIntelligenceApi, type OptionMetrics, type OptionsView } from '@/api/optionsIntelligence';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { useAuthStore } from '@/stores/authStore';
import OptionsDataControls from '@/components/options-intelligence/OptionsDataControls.vue';
import OptionHelp from '@/components/options-intelligence/OptionHelp.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Input } from '@/components/ui/input';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import LoadingButton from '@/components/app/LoadingButton.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import StockDetailDialog, { type StockDetailRecord } from '@/components/stocks/StockDetailDialog.vue';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import { eventLabels, formatOptionNumber as num, formatOptionPct as pct } from '@/components/options-intelligence/labels';
const auth = useAuthStore();
const items = ref<OptionMetrics[]>([]), query = ref(''), eventType = ref(''), sort = ref('unusualActivity');
const loading = ref(false), error = ref<ParsedApiError | null>(null), selected = ref<StockDetailRecord | null>(null);
const pending = ref('');
const mode = ref<OptionsView>('official'), requestedDate = ref(''), selectedDate = ref('');
const dates = ref<string[]>([]), reason = ref<string | null>(null);
let generation = 0;
const filtered = computed(() => items.value.filter(r => r.symbol.toLowerCase().includes(query.value.toLowerCase()) &&
  (!eventType.value || r.eventTypes?.includes(eventType.value))).sort((a, b) => {
    const key = sort.value as 'bearishDemand' | 'unusualActivity' | 'liquidityRisk';
    const x = a.scores?.[key].value, y = b.scores?.[key].value;
    return x == null ? y == null ? a.symbol.localeCompare(b.symbol) : 1 : y == null ? -1 : y - x || a.symbol.localeCompare(b.symbol);
  }));
async function load() {
  const version = ++generation;
  loading.value = true; error.value = null; items.value = []; reason.value = null;
  try {
    const response = await optionsIntelligenceApi.scan({ view: mode.value, tradeDate: mode.value === 'official' ? requestedDate.value || undefined : undefined });
    if (version !== generation) return;
    items.value = response.items; dates.value = response.availableDates ?? [];
    selectedDate.value = response.tradeDate ?? ''; reason.value = response.reason ?? null;
  }
  catch (e) { if (version === generation) error.value = getParsedApiError(e); }
  finally { if (version === generation) loading.value = false; }
}
async function run() {
  try { pending.value = (await optionsIntelligenceApi.run(mode.value)).taskId; }
  catch (e) { error.value = getParsedApiError(e); }
}
function open(row: OptionMetrics) {
  selected.value = { id: 0, code: row.symbol, name: null, market_type: 'US', created_at: '', updated_at: row.observedAt ?? '' };
}
watch([mode, requestedDate], () => { selected.value = null; void load(); }, { immediate: true });
onBeforeUnmount(() => { generation++; });
</script>
<template>
  <div
    class="min-w-0 space-y-5"
    data-testid="options-scanner"
  >
    <PageHeader
      variant="section"
      title="期权情报"
      en="Options Intelligence"
      description="Nasdaq-100 与美股自选的期权异常、保护需求和流动性研究。"
    >
      <template #actions>
        <OptionsDataControls
          :mode="mode"
          :date="selectedDate"
          :dates="dates"
          @update:mode="mode = $event"
          @update:date="requestedDate = $event"
        />
        <LoadingButton
          :loading="loading"
          variant="outline"
          @click="load"
        >
          刷新列表
        </LoadingButton>
        <Button
          v-if="auth.currentUser?.role === 'admin'"
          @click="run"
        >
          运行{{ mode === 'preview' ? '预演' : '正式扫描' }}
        </Button>
      </template>
    </PageHeader>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      @dismiss="error = null"
    />
    <p
      v-if="pending"
      class="text-sm"
    >
      已提交任务 <RouterLink
        class="underline"
        to="/tasks/runs"
      >
        {{ pending }}
      </RouterLink>；完成后刷新列表。
    </p>
    <div class="grid items-end gap-3 sm:grid-cols-3">
      <div>
        <label
          for="options-search"
          class="mb-2 block text-sm"
        >股票搜索</label><Input
          id="options-search"
          v-model="query"
          placeholder="SPY / NVDA…"
        />
      </div><FieldSelect
        v-model="sort"
        label="按评分排序"
        :options="[{ value: 'unusualActivity', label: '异常交易活动 ↓' }, { value: 'bearishDemand', label: '看跌保护需求 ↓' }, { value: 'liquidityRisk', label: '流动性风险 ↓' }]"
      /><FieldSelect
        v-model="eventType"
        label="异常类型"
        :options="[{ value: '', label: '全部' }, ...Object.entries(eventLabels).map(([value, label]) => ({ value, label }))]"
      />
    </div>
    <div class="overflow-x-auto rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>
              <OptionHelp
                label="股票"
                compact
              />
            </TableHead><TableHead>
              <OptionHelp
                label="股价 ($)"
                compact
              />
            </TableHead><TableHead>
              <OptionHelp
                label="看跌保护需求"
                compact
              />
            </TableHead><TableHead>
              <OptionHelp
                label="异常活动"
                compact
              />
            </TableHead><TableHead>
              <OptionHelp
                label="流动性风险"
                compact
              />
            </TableHead><TableHead>
              <OptionHelp
                label="25Δ Skew"
                compact
              />
            </TableHead><TableHead>
              <OptionHelp
                label="Put/Call Volume"
                compact
              />
            </TableHead><TableHead>
              <OptionHelp
                label="主要异常"
                compact
              />
            </TableHead><TableHead>
              <OptionHelp
                label="证据"
                compact
              />
            </TableHead><TableHead>
              <OptionHelp
                label="更新时间"
                compact
              />
            </TableHead>
          </TableRow>
        </TableHeader><TableBody>
          <TableRow
            v-for="r in filtered"
            :key="r.symbol"
          >
            <TableCell>
              <Button
                variant="link"
                class="h-auto p-0 font-semibold"
                @click="open(r)"
              >
                {{ r.symbol }}
              </Button>
            </TableCell><TableCell>{{ num(r.underlyingPrice) }}</TableCell><TableCell
              class="text-red-600 dark:text-red-400"
              :class="{ 'bg-red-500/10 font-bold': (r.scores?.bearishDemand.value ?? 0) >= 80 }"
            >
              {{ num(r.scores?.bearishDemand.value, 1) }}
            </TableCell><TableCell
              class="text-amber-600 dark:text-amber-400"
              :class="{ 'bg-amber-500/10 font-bold': (r.scores?.unusualActivity.value ?? 0) >= 80 }"
            >
              {{ num(r.scores?.unusualActivity.value, 1) }}
            </TableCell><TableCell
              class="text-orange-600 dark:text-orange-400"
              :class="{ 'bg-orange-500/10 font-bold': (r.scores?.liquidityRisk.value ?? 0) >= 80 }"
            >
              {{ num(r.scores?.liquidityRisk.value, 1) }}
            </TableCell><TableCell>{{ pct(r.skew30D) }}</TableCell><TableCell>{{ num(r.putCallVolumeRatio) }}</TableCell><TableCell>{{ r.topEvent ? eventLabels[r.topEvent.eventType] : r.status === 'failed' ? '采集失败' : r.status === 'not_scanned' ? '尚未采集' : '无满足规则的异常' }}</TableCell><TableCell>
              {{ r.evidenceGrade ?? 'N/A' }}<p class="text-xs text-muted-foreground">
                {{ r.status === 'warming_up' ? `预热 ${r.historyDays}D` : '' }}
              </p>
            </TableCell><TableCell class="text-xs">
              {{ formatDateTimeInDisplayTimezone(r.observedAt) }}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table><p
        v-if="!filtered.length"
        class="p-6 text-center text-sm text-muted-foreground"
      >
        {{ reason || '暂无符合筛选的股票' }}
      </p>
    </div>
    <p class="text-xs text-muted-foreground">
      三个评分互相独立，不相加。高看跌需求不代表下跌概率或真实净空头。N/A 表示缺少评分所需证据。监控范围：数据库维护的当前 Nasdaq-100 成分股与您的美股自选。历史按当前可见范围过滤；盘中预演为临时研究，正式数据按交易日保存。
    </p>
    <StockDetailDialog
      :stock="selected"
      kind="research"
      initial-tab="options"
      :options-view="mode"
      :options-date="mode === 'official' ? selectedDate || undefined : undefined"
      @update:open="selected = null"
    />
  </div>
</template>
