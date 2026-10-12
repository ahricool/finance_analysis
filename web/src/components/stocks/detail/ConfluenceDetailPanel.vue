<script setup lang="ts">
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import { metricHint } from '@/utils/metricHints';
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import type { StockDetailPanelProps } from './types';
import { confluenceApi as api, type ConfluenceItem, type SignalKey } from '@/api/confluence';
import DailyKLineCard from '@/components/market-data/DailyKLineCard.vue';
import { formatDateTime } from '@/utils/format';
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
const keys: SignalKey[] = ['industry', 'trend', 'quant', 'etf', 'dragonTiger'];
const labels: Record<SignalKey, string> = { industry: '行业', trend: '趋势', quant: 'Quant', etf: 'ETF', dragonTiger: '龙虎榜资金' };
const states = { positive: '正向', neutral: '中性', negative: '负向', unavailable: '无数据' };
const fields: Record<SignalKey, [string, string][]> = {
  industry: [['industryName', '行业'], ['strengthRank', '排名'], ['strengthScore', '强度'], ['state', '状态'], ['rankChange1D', '1D 排名变化'], ['rankChange3D', '3D 排名变化'], ['rankChange5D', '5D 排名变化'], ['momentumAcceleration5D', '5D 增强'], ['membersObservedAt', '成分观测时间']],
  trend: [['trendLifecycle', 'Lifecycle'], ['state', 'State'], ['trendScore', 'Trend Score'], ['rank', '排名'], ['previousRank', '前次排名'], ['previousTradeDate', '前次日期'], ['trendDurationDays', '持续天数'], ['fragilityScore', 'Fragility'], ['trendAcceleration', 'Acceleration'], ['trendQuality', 'Quality'], ['rsScore', 'RS Score']],
  quant: [['universeRank', '排名'], ['finalScore', 'Final Score'], ['signal', 'Signal'], ['predictedReturn', 'Prediction'], ['crossSectionScore', '横截面分数'], ['modelVersion', '模型版本']],
  etf: [['code', '关联 ETF'], ['rank', '排名'], ['state', 'State'], ['compositeScore', 'Composite'], ['entryScore', 'Entry Score'], ['rankChange1D', '1D 排名变化'], ['rankChange3D', '3D 排名变化'], ['rankChange5D', '5D 排名变化']],
  dragonTiger: [['rangeDays', '榜单窗口（天）'], ['netInflow', '净流入'], ['institutionNetInflow', '机构资金'], ['hotMoneyNetInflow', '游资资金']],
};
function flowRecords(row: ConfluenceItem) { return (row.signals.dragonTiger.evidence.records ?? []) as Array<Record<string, unknown>>; }
function flowConcepts(row: ConfluenceItem) { return (row.signals.dragonTiger.evidence.conceptFlows ?? []) as Array<Record<string, unknown>>; }
function evidence(row: ConfluenceItem, key: SignalKey, field: string) { return row.signals[key].evidence[field] ?? '—'; }
</script>
<template>
  <div
    class="space-y-4"
    data-testid="confluence-detail-panel"
  >
    <p class="text-sm text-muted-foreground">
      正式共振快照 · 目标 {{ result?.tradeDate || context?.tradeDate || '最新可用日期' }} · {{ result?.algorithmVersion }} · 各来源以独立日期为准。
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
    />
    <p
      v-else-if="!selected"
      class="text-sm text-muted-foreground"
    >
      {{ supported ? '该股票在所选日期暂无正式共振证据。' : '此市场暂不支持共振研究。' }}
    </p>
    <Button
      v-if="error"
      variant="outline"
      @click="load"
    >
      重试
    </Button>
    <template v-if="selected">
      <DailyKLineCard
        :symbol="selected.code"
        :highlight-date="result?.tradeDate || undefined"
      />
      <p>共振 {{ selected.confluenceScore }} = 各维度贡献合计 / {{ selected.availableWeight }} × 100。正向 {{ selected.positiveSignalCount }} / 有效 {{ selected.availableSignalCount }}。</p>
      <section
        v-for="key in keys"
        :key="key"
        class="border-t pt-4 space-y-2"
      >
        <h3 class="font-semibold">
          {{ labels[key] }} · {{ states[selected.signals[key].status] }} · {{ selected.signals[key].score ?? '—' }}/{{ selected.signals[key].weight }}
        </h3>
        <p class="text-xs text-muted-foreground">
          来源 {{ selected.signals[key].sourceModule }} · 数据日期 {{ selected.signals[key].tradeDate ?? '缺失' }} · 源生成时间 {{ selected.signals[key].sourceGeneratedAt ? formatDateTime(selected.signals[key].sourceGeneratedAt!) : '缺失' }}
        </p>
        <dl
          v-if="selected.signals[key].status !== 'unavailable'"
          class="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3"
        >
          <div
            v-for="[field, label] in fields[key]"
            :key="field"
          >
            <dt class="text-muted-foreground">
              <IndicatorHelpLabel
                :scope="`confluence-${key}`"
                :label="label"
                :description="metricHint(`confluence-${key}`, field)"
                compact
              />
            </dt><dd>{{ evidence(selected, key, field) }}</dd>
          </div>
        </dl>
        <div
          v-if="key === 'dragonTiger' && selected.signals[key].status !== 'unavailable'"
          class="text-sm space-y-1"
        >
          <p>最近记录（1D 与原生 3D 榜单分别展示，不累计）：</p>
          <p
            v-for="(record, index) in flowRecords(selected)"
            :key="index"
          >
            {{ record.tradeDate }} · {{ record.rangeDays }}D · 净额 {{ record.netInflow ?? '缺失' }} CNY · 机构 {{ record.institutionNetInflow ?? '缺失' }} · 游资 {{ record.hotMoneyNetInflow ?? '缺失' }}
          </p>
          <p
            v-for="(concept, index) in flowConcepts(selected)"
            :key="index"
          >
            概念 {{ concept.name }}：榜单分摊净额 {{ concept.netInflow ?? '缺失' }} CNY（仅解释）
          </p>
        </div>
        <ul class="list-disc pl-5 text-sm space-y-1">
          <li
            v-for="reason in selected.signals[key].reasons"
            :key="reason"
          >
            {{ reason }}
          </li>
        </ul>
      </section>
      <section class="border-t pt-4">
        <h3 class="font-semibold mb-2">
          Why Confluence
        </h3><ul class="list-disc pl-5 text-sm space-y-1">
          <li
            v-for="reason in selected.reasons"
            :key="reason"
          >
            {{ reason }}
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
