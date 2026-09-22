<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import { trendFollowingApi } from '@/api/trendFollowing';
import { etfRotationApi } from '@/api/etfRotation';
import { quantApi } from '@/api/quant';
import { industryStrengthApi } from '@/api/industryStrength';
import { tradeEngineApi, type TradeSignal } from '@/api/holdings';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';

const props = defineProps<{ symbol: string; market: string; positionId?: number }>();
interface Evidence {
  title: string; date: string; summary: string; reasons: string[];
  path: string; query: Record<string, string>;
}
interface Source {
  key: string; title: string; loading: boolean; error: ParsedApiError | null; items: Evidence[];
}
const sources = ref<Source[]>([]);
const signals = ref<TradeSignal[]>([]);
const signalLoading = ref(false);
const signalError = ref<ParsedApiError | null>(null);
const supported = computed(() => props.market === 'CN' || props.market === 'US');
const dates = computed(() => new Set(sources.value.flatMap(source => source.items.map(item => item.date))));
let generation = 0;
let signalRequest = 0;
onBeforeUnmount(() => { generation++; signalRequest++; });
const number = (value: number | null | undefined) => value == null ? '—' : value.toFixed(2);

async function loadSource(source: Source, version = generation) {
  const { symbol, market } = props;
  if (market !== 'CN' && market !== 'US') return;
  source.loading = true;
  source.error = null;
  source.items = [];
  try {
    let items: Evidence[] = [];
    if (source.key === 'trend') {
      const { latest } = await trendFollowingApi.detail(symbol, market, 1);
      if (latest) items = [{ title: '趋势跟踪', date: latest.tradeDate,
        summary: `${latest.state} · 排名 ${latest.rank ?? '—'} · Alpha ${number(latest.alphaScore)}`,
        reasons: latest.reasons || [], path: '/research/trend-following',
        query: { market, symbol, tradeDate: latest.tradeDate } }];
    } else if (source.key === 'etf') {
      const { latest } = await etfRotationApi.detail(symbol, market, 1);
      if (latest) items = [{ title: 'ETF 轮动', date: latest.tradeDate,
        summary: `${latest.state} · ${latest.action || '无动作'} · 排名 ${latest.rank ?? '—'}`,
        reasons: [`动量分 ${number(latest.momentumScore)}`, `入选候选 ${latest.isCandidate ? '是' : '否'}`],
        path: '/research/etf-rotation', query: { market, symbol, tradeDate: latest.tradeDate } }];
    } else if (source.key === 'quant') {
      const item = await quantApi.signal(symbol, market);
      if (item) items = [{ title: 'Quant', date: item.tradeDate,
        summary: `${item.signal} · 排名 ${item.universeRank ?? '—'} · 得分 ${number(item.finalScore)}`,
        reasons: [`模型 ${item.modelVersion}`, ...(item.reasons || [])],
        path: `/research/quant/signals/${encodeURIComponent(symbol)}`, query: { market, tradeDate: item.tradeDate } }];
    } else if (source.key === 'industry') {
      const rows = await industryStrengthApi.stockContext(symbol);
      items = rows.map(item => ({ title: item.industryName, date: item.tradeDate,
        summary: `${item.state} · 排名 ${item.strengthRank ?? '—'} · 强度 ${number(item.strengthScore)}`,
        reasons: [`当前成分观测时间 ${formatDateTimeInDisplayTimezone(item.membersObservedAt)}`, '行业背景不代表个股交易建议'],
        path: '/research/industry-strength', query: { industry: item.industryCode, tradeDate: item.tradeDate } }));
    }
    if (version === generation) source.items = items;
  } catch (error) {
    if (version === generation && getParsedApiError(error).status !== 404) source.error = getParsedApiError(error);
  } finally {
    if (version === generation) source.loading = false;
  }
}
async function loadSignals() {
  const version = generation;
  const request = ++signalRequest;
  const { positionId, market, symbol } = props;
  signals.value = [];
  signalError.value = null;
  if (positionId == null || !supported.value) { signalLoading.value = false; return; }
  signalLoading.value = true;
  try {
    const rows = await tradeEngineApi.signals(market, String(positionId));
    if (version === generation && request === signalRequest) {
      signals.value = rows.filter(row => row.positionId === String(positionId) && row.symbol === symbol);
    }
  } catch (error) {
    if (version === generation && request === signalRequest) signalError.value = getParsedApiError(error);
  } finally {
    if (version === generation && request === signalRequest) signalLoading.value = false;
  }
}
watch(() => [props.symbol, props.market, props.positionId], () => {
  generation++;
  sources.value = supported.value ? [
    ['trend', '趋势跟踪'], ['etf', 'ETF 轮动'], ['quant', 'Quant'],
    ...(props.market === 'CN' ? [['industry', '行业背景']] : []),
  ].map(([key, title]) => ({ key: key!, title: title!, loading: true, error: null, items: [] })) : [];
  sources.value.forEach(source => { void loadSource(source); });
  void loadSignals();
}, { immediate: true });
</script>

<template>
  <section
    class="space-y-3 border-t pt-4"
    data-testid="research-evidence"
    aria-label="研究证据"
  >
    <h3 class="font-semibold">
      研究证据 · {{ symbol }}
    </h3>
    <p class="text-xs text-muted-foreground">
      以下为各模块最新正式结果，日期可能不同；研究信号与个人调仓建议独立展示，不合成为买卖结论。
    </p>
    <p
      v-if="!supported"
      class="text-sm text-muted-foreground"
    >
      当前研究模块仅覆盖 A 股与美股，港股暂无研究证据。
    </p>
    <p
      v-if="dates.size > 1"
      class="text-sm text-amber-600"
    >
      各模块数据日期不一致，请按卡片日期查看。
    </p>
    <div class="grid grid-cols-2 gap-3">
      <article
        v-for="source in sources"
        :key="source.key"
        class="space-y-2 rounded-lg border p-3"
        :data-testid="`evidence-${source.key}`"
      >
        <h4 class="text-sm font-medium">
          {{ source.title }}
        </h4>
        <p
          v-if="source.loading"
          class="text-sm text-muted-foreground"
        >
          加载中…
        </p>
        <template v-else-if="source.error">
          <ApiErrorAlert :error="source.error" />
          <Button
            size="sm"
            variant="outline"
            @click="loadSource(source)"
          >
            重试{{ source.title }}
          </Button>
        </template>
        <p
          v-else-if="!source.items.length"
          class="text-sm text-muted-foreground"
        >
          暂无正式结果或不在该模块覆盖范围内
        </p>
        <div
          v-for="item in source.items"
          :key="item.title"
          class="space-y-1 text-sm"
        >
          <p>{{ item.title }} · 正式 · {{ item.date }}</p>
          <p>{{ item.summary }}</p>
          <p
            v-for="reason in item.reasons"
            :key="reason"
            class="text-xs text-muted-foreground"
          >
            {{ reason }}
          </p>
          <RouterLink
            :to="{ path: item.path, query: item.query }"
            class="inline-block text-xs underline"
          >
            查看来源详情
          </RouterLink>
        </div>
      </article>
    </div>
    <div
      v-if="positionId != null"
      class="space-y-2"
      data-testid="signal-evidence"
    >
      <h4 class="text-sm font-medium">
        历史调仓建议与当时依据
      </h4>
      <p class="text-xs text-muted-foreground">
        仅展示当时保存的信号依据，不使用上方最新研究结果解释历史建议。实际操作见下方操作记录，可按时间对照。
      </p>
      <p
        v-if="signalLoading"
        class="text-sm"
      >
        加载中…
      </p>
      <template v-else-if="signalError">
        <ApiErrorAlert :error="signalError" />
        <Button
          size="sm"
          variant="outline"
          @click="loadSignals"
        >
          重试历史建议
        </Button>
      </template>
      <p
        v-else-if="!signals.length"
        class="text-sm text-muted-foreground"
      >
        暂无正式调仓信号；无信号不代表没有执行评估。
      </p>
      <details
        v-for="signal in signals"
        :key="signal.id"
        class="rounded-lg border p-3 text-sm"
      >
        <summary class="cursor-pointer">
          {{ formatDateTimeInDisplayTimezone(signal.evaluatedAt) }} · {{ signal.action }} · 目标 {{ signal.suggestedTargetQuantity ?? '—' }} 股
        </summary>
        <div class="mt-2 space-y-2">
          <p>策略 {{ signal.strategyKey }} · 版本 {{ signal.strategyVersion }}</p>
          <p>{{ signal.reason }}</p>
          <p v-if="signal.llmReason && signal.llmReason !== signal.reason">
            LLM 判断：{{ signal.llmReason }}
          </p>
          <p>当时持仓 {{ signal.evidence.currentQuantity ?? '未记录' }} → 目标 {{ signal.evidence.targetQuantity ?? '未记录' }}</p>
          <p v-if="signal.evidence.portfolioReason">
            组合判断：{{ signal.evidence.portfolioReason }}
          </p>
          <p
            v-for="(item, index) in signal.evidence.strategySignals || []"
            :key="index"
          >
            {{ item.strategyKey }} · {{ item.action }} · {{ item.reason }}
          </p>
          <p v-if="signal.evidence.portfolioRisk">
            当时总仓位 {{ signal.evidence.portfolioRisk.grossExposure ?? '未记录' }} · 上限 {{ signal.evidence.portfolioRisk.maxGrossExposure ?? '未记录' }}
          </p>
          <p v-if="signal.evidence.portfolioRisk?.position">
            当时个股权重 {{ signal.evidence.portfolioRisk.position.weight ?? '未记录' }} · 风险 {{ signal.evidence.portfolioRisk.position.openRisk ?? '未记录' }}
          </p>
        </div>
      </details>
    </div>
  </section>
</template>
