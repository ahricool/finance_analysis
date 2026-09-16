<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue';
import { industryStrengthApi as api, type IndustryRanking, type IndustryHistory, type IndustryDetail, type Constituents } from '@/api/industryStrength';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import IndustryRankingTable from '@/components/industry-strength/IndustryRankingTable.vue';
import IndustryCharts from '@/components/industry-strength/IndustryCharts.vue';
import IndustryDetailPanel from '@/components/industry-strength/IndustryDetailPanel.vue';
import { pct } from '@/components/industry-strength/display';
import { formatDateTime } from '@/utils/format';
const ranking = shallowRef<IndustryRanking | null>(null);
const history = shallowRef<IndustryHistory>({ dates: [], items: [] });
const detail = shallowRef<IndustryDetail | null>(null);
const constituents = shallowRef<Constituents | null>(null);
const dates = ref<string[]>([]); const date = ref(''); const selected = ref('');
const loading = ref(true); const detailLoading = ref(false); const membersLoading = ref(false);
const error = shallowRef<ParsedApiError | null>(null); const auxiliaryError = shallowRef<ParsedApiError | null>(null);
const detailError = shallowRef<ParsedApiError | null>(null); const membersError = shallowRef<ParsedApiError | null>(null);
let request = 0; let selection = 0;
const rows = computed(() => ranking.value?.items ?? []);
const top = computed(() => [...rows.value].sort((a, b) => a.strengthRank - b.strengthRank)[0]);
const accelerating = computed(() => [...rows.value].filter(r => r.momentumAcceleration5D > 0).sort((a, b) => b.momentumAcceleration5D - a.momentumAcceleration5D)[0]);
const cooling = computed(() => [...rows.value].filter(r => r.momentumAcceleration5D < 0).sort((a, b) => a.momentumAcceleration5D - b.momentumAcceleration5D)[0]);
const summary = computed(() => [
  ['最强行业', top.value?.industryName ?? '—', top.value ? `Strength ${top.value.strengthScore.toFixed(1)}` : ''],
  ['加速最快', accelerating.value?.industryName ?? '暂无', pct(accelerating.value?.momentumAcceleration5D)],
  ['退潮最快', cooling.value?.industryName ?? '暂无', pct(cooling.value?.momentumAcceleration5D)],
  ['持续强势', String(rows.value.filter(r => r.state === 'STRONG').length), 'RS 与广度共同确认'],
  ['上涨行业 / 有效行业', `${rows.value.filter(r => r.ret1D > 0).length} / ${rows.value.length}`, '按行业指数当日涨跌'],
  ['数据有效日期', ranking.value?.tradeDate ?? '—', 'A 股完整收盘截面'],
]);
async function selectIndustry(code: string) {
  const token = ++selection; selected.value = code; detail.value = null; constituents.value = null;
  detailError.value = null; membersError.value = null; detailLoading.value = true; membersLoading.value = true;
  await Promise.allSettled([
    api.detail(code, ranking.value?.tradeDate ?? undefined).then(data => { if (token === selection) detail.value = data; }).catch(cause => { if (token === selection) detailError.value = getParsedApiError(cause); }).finally(() => { if (token === selection) detailLoading.value = false; }),
    api.constituents(code).then(data => { if (token === selection) constituents.value = data; }).catch(cause => { if (token === selection) membersError.value = getParsedApiError(cause); }).finally(() => { if (token === selection) membersLoading.value = false; }),
  ]);
}
async function load() {
  const token = ++request; ++selection; loading.value = true; error.value = null; auxiliaryError.value = null;
  ranking.value = null; detail.value = null; constituents.value = null; selected.value = ''; history.value = { dates: [], items: [] };
  detailError.value = null; membersError.value = null; detailLoading.value = false; membersLoading.value = false;
  const datesPromise = api.dates().then(data => { if (token === request) dates.value = data; }).catch(cause => { if (token === request) auxiliaryError.value = getParsedApiError(cause); });
  try {
    const data = await api.ranking(date.value || undefined);
    if (token !== request) return;
    ranking.value = data;
    if (data.items.length && data.tradeDate) {
      void selectIndustry(data.items[0]!.industryCode);
      try { const result = await api.history(data.tradeDate); if (token === request) history.value = result; }
      catch (cause) { if (token === request) auxiliaryError.value = getParsedApiError(cause); }
    }
  } catch (cause) { if (token === request) error.value = getParsedApiError(cause); }
  finally { if (token === request) loading.value = false; }
  await datesPromise;
}
onMounted(load);
onBeforeUnmount(() => { request++; selection++; });
</script>
<template>
  <div
    class="space-y-5"
    data-testid="industry-strength-page"
  >
    <PageHeader
      title="行业强度"
      description="Industry Strength · A 股行业地图 · 观察相对强弱、加速度与内部广度"
    >
      <template #actions>
        <div class="flex items-center gap-2">
          <AppDatePicker
            v-model="date"
            class="w-56"
            data-testid="industry-date-picker"
            placeholder="最新快照"
            :available-dates="dates"
            @update:model-value="load"
          /><Button
            variant="outline"
            :disabled="loading"
            @click="load"
          >
            刷新
          </Button>
        </div>
      </template>
    </PageHeader>
    <p class="text-xs leading-6 text-muted-foreground">
      数据源：同花顺金融数据 API / 扶摇 · 成分股行情：FA 现有 A 股行情能力 · 基准：沪深300（000300.SH）。Strength 与 State 描述市场环境，不构成买入建议。
    </p>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重新加载"
      @action="load"
      @dismiss="error = null"
    />
    <AppApiErrorAlert
      v-if="auxiliaryError"
      :error="auxiliaryError"
      action-label="重试日期与历史"
      @action="load"
      @dismiss="auxiliaryError = null"
    />
    <div
      v-if="loading && !ranking"
      class="grid grid-cols-3 gap-3"
      data-testid="industry-loading"
    >
      <Skeleton
        v-for="i in 6"
        :key="i"
        class="h-28"
      /><Skeleton class="col-span-3 h-80" />
    </div>
    <p
      v-else-if="ranking && !rows.length"
      class="rounded-xl border py-16 text-center text-muted-foreground"
      data-testid="industry-empty"
    >
      所选日期暂无行业强度快照。正式结果由收盘任务生成，覆盖不足时不会发布。
    </p>
    <template v-if="rows.length">
      <p
        v-if="rows.some(row => row.quality.breadthStatus === 'unavailable_historical_members')"
        class="rounded-lg border border-amber-500/40 p-3 text-sm text-amber-600"
      >
        历史补算：按当前行业目录计算所选日指数强度；缺少当日成分记录，历史广度不可用。
      </p>
      <p
        v-if="!date && ranking?.tradeDate !== ranking?.expectedTradeDate"
        class="rounded-lg border border-amber-500/40 p-3 text-sm text-amber-600"
      >
        最新完整交易日为 {{ ranking?.expectedTradeDate }}，当前展示 {{ ranking?.tradeDate }} 的已保存结果。
      </p>
      <div class="grid grid-cols-3 gap-3 min-[100rem]:grid-cols-6">
        <Card
          v-for="[label, value, hint] in summary"
          :key="label"
        >
          <CardContent class="pt-4">
            <p class="text-xs text-muted-foreground">
              {{ label }}
            </p><p class="my-2 text-xl font-semibold">
              {{ value }}
            </p><p class="text-xs text-muted-foreground">
              {{ hint }}
            </p>
          </CardContent>
        </Card>
      </div>
      <p class="text-xs text-muted-foreground">
        生成时间：{{ formatDateTime(top?.updatedAt) }} · 行业覆盖 {{ top?.quality.rankedCount }} / {{ top?.quality.catalogCount }} · 首次运行积累历史前，排名变化及持续强势确认可能缺失。
      </p>
      <details
        v-if="top && Object.keys(top.quality.excluded).length"
        class="rounded-lg border p-3 text-sm"
      >
        <summary>未参与排名的行业（{{ Object.keys(top.quality.excluded).length }}）</summary><p
          v-for="(reason, code) in top.quality.excluded"
          :key="code"
          class="mt-2 text-xs"
        >
          {{ code }}：{{ reason }}
        </p>
      </details>
      <section class="space-y-3">
        <h2 class="text-lg font-semibold">
          行业强度 Rank
        </h2><p class="text-xs text-muted-foreground">
          1 为最强 · 排名变化为历史排名 − 当前排名 · RS / 加速度以百分点理解 · 点击列名排序，点击行业查看详情
        </p><IndustryRankingTable
          :rows="rows"
          :selected="selected"
          @select="selectIndustry"
        />
      </section>
      <IndustryCharts
        :rows="rows"
        :history="history"
        :selected="selected"
        @select="selectIndustry"
      />
      <AppApiErrorAlert
        v-if="detailError"
        :error="detailError"
        action-label="重试行业详情"
        @action="selectIndustry(selected)"
        @dismiss="detailError = null"
      />
      <Skeleton
        v-if="detailLoading"
        class="h-64"
      />
      <IndustryDetailPanel
        v-if="detail"
        :detail="detail"
        :constituents="constituents"
      />
      <p
        v-if="membersLoading"
        class="text-sm text-muted-foreground"
      >
        正在加载当前成分股…
      </p>
      <AppApiErrorAlert
        v-if="membersError"
        :error="membersError"
        action-label="重试当前成分"
        @action="selectIndustry(selected)"
        @dismiss="membersError = null"
      />
    </template>
  </div>
</template>
