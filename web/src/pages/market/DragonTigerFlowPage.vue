<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';
import { useAuth } from '@/composables/useAuth';
import { getParsedApiError } from '@/api/error';
import { useDragonTigerFlow } from '@/composables/useDragonTigerFlow';
import { dragonTigerFlowApi, flowBoardLabels, type FlowBoard } from '@/api/dragonTigerFlow';
import { money, exportObservation } from '@/components/dragon-tiger-flow/display';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import FlowCharts from '@/components/dragon-tiger-flow/FlowCharts.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { formatDateTime } from '@/utils/format';
const { filters, data, dates, error, datesError, loading, selected, stock, concept, stocks, stockRows, load, loadDates, change } = useDragonTigerFlow();
const { currentUser } = useAuth();
const submitting = ref(false), taskId = ref('');
const runError = ref<ReturnType<typeof getParsedApiError> | null>(null);
async function submit(backfill = false) {
  submitting.value = true; runError.value = null; taskId.value = '';
  try { taskId.value = (await dragonTigerFlowApi.run(backfill ? { backfill_days: 20, missing_only: true } : { trade_date: filters.value.endDate || undefined })).taskId; }
  catch (e) { runError.value = getParsedApiError(e); }
  finally { submitting.value = false; }
}
const contributions = computed(() => data.value?.evidence.filter(r => r.symbol === stock.value && r.conceptId === selected.value) ?? []);
const search = ref(''), direction = ref('all'), descending = ref(true);
const stockSort = ref<'name' | 'netValue' | 'days'>('netValue');
const stockDescending = ref(true);
const sortedStocks = computed(() => stocks.value.slice().sort((a, b) => {
  const av = stockSort.value === 'days' ? a.rows.length : a[stockSort.value as 'name' | 'netValue'];
  const bv = stockSort.value === 'days' ? b.rows.length : b[stockSort.value as 'name' | 'netValue'];
  if (av === null || bv === null) return Number(av === null) - Number(bv === null) || a.symbol.localeCompare(b.symbol);
  const comparison = typeof av === 'string' ? av.localeCompare(String(bv)) : av - Number(bv);
  return comparison * (stockDescending.value ? -1 : 1) || a.symbol.localeCompare(b.symbol);
}));
function sortStocks(key: 'name' | 'netValue' | 'days') {
  stockDescending.value = stockSort.value === key ? !stockDescending.value : key !== 'name';
  stockSort.value = key;
}
const boards: FlowBoard[] = ['all', 'org', 'hot_money'];
const windows = [5, 10, 20] as const;
const ranking = computed(() => (data.value?.concepts ?? []).filter(c => c.name.includes(search.value)
  && (direction.value === 'all' || (direction.value === 'positive' ? (c.netValue ?? 0) > 0 : (c.netValue ?? 0) < 0)))
  .slice().sort((a, b) => Number(a.netValue === null) - Number(b.netValue === null)
    || (descending.value ? -1 : 1) * ((a.netValue ?? 0) - (b.netValue ?? 0)) || a.id.localeCompare(b.id)));
const metrics = computed(() => data.value ? [
  ['上榜股票', `${data.value.summary.stockCount}只`], ['买入额', money(data.value.summary.buyValue)],
  ['卖出额', money(data.value.summary.sellValue)], ['所选口径净额', money(data.value.summary.netValue)],
  ['机构净额（独立口径）', money(data.value.summary.orgNetValue)], ['游资净额（独立口径）', money(data.value.summary.hotMoneyNetValue)],
  ['Top5正流入占比', data.value.summary.top5Concentration == null ? '—' : `${(data.value.summary.top5Concentration * 100).toFixed(1)}%`],
] : []);
const generatedAt = computed(() => data.value?.sourceQuality.map(q => q.generatedAt).sort().at(-1));
const hotDetails = computed(() => data.value?.hotMoneyDetails.filter(r => r.symbol === stock.value) ?? []);
const stockName = computed(() => stockRows.value[0]?.name ?? stock.value);
const moneyClass = (v: number | null) => v == null ? 'text-muted-foreground' : v >= 0 ? 'text-[var(--market-up)]' : 'text-[var(--market-down)]';
onMounted(() => { void load(); void loadDates(); });
</script>

<template>
  <div
    class="min-w-0 space-y-4"
    data-testid="dragon-tiger-flow-page"
  >
    <PageHeader
      title="龙虎榜资金流向"
      description="从概念净额轨迹穿透到股票贡献，观察龙虎榜样本资金变化。非投资建议。"
    >
      <template #actions>
        <AppDatePicker
          :model-value="filters.endDate"
          :available-dates="dates"
          placeholder="最新快照"
          class="w-48"
          @update:model-value="change({ endDate: $event })"
        />
        <Button
          v-if="filters.endDate"
          variant="outline"
          @click="change({ endDate: '' })"
        >
          回到最新
        </Button>
        <Button
          variant="outline"
          :disabled="!data || loading"
          @click="data && exportObservation(data)"
        >
          导出资金截面
        </Button>
      </template>
    </PageHeader>
    <div class="flex flex-wrap items-center gap-3">
      <div
        class="flex gap-1"
        aria-label="榜单类型"
      >
        <Button
          v-for="board in boards"
          :key="board"
          :variant="filters.board === board ? 'default' : 'outline'"
          :aria-pressed="filters.board === board"
          @click="change({ board })"
        >
          {{ flowBoardLabels[board] }}
        </Button>
      </div>
      <div
        v-if="filters.rangeDays === 1"
        class="flex gap-1"
        aria-label="交易日窗口"
      >
        <Button
          v-for="days in windows"
          :key="days"
          :variant="filters.days === days ? 'secondary' : 'ghost'"
          :aria-pressed="filters.days === days"
          @click="change({ days })"
        >
          {{ days }}日
        </Button>
      </div>
      <Button
        :variant="filters.rangeDays === 1 ? 'secondary' : 'ghost'"
        :aria-pressed="filters.rangeDays === 1"
        @click="change({ rangeDays: 1 })"
      >
        仅1日榜
      </Button>
      <Button
        :variant="filters.rangeDays === 3 ? 'secondary' : 'ghost'"
        :aria-pressed="filters.rangeDays === 3"
        @click="change({ rangeDays: 3 })"
      >
        3日榜截面
      </Button>
    </div>
    <div
      v-if="currentUser?.role === 'admin'"
      class="flex items-center gap-3 rounded-lg border p-3 text-sm"
    >
      <Button
        variant="outline"
        :disabled="submitting"
        @click="submit()"
      >
        采集所选收盘日
      </Button>
      <Button
        variant="outline"
        :disabled="submitting"
        @click="submit(true)"
      >
        补齐最近20交易日
      </Button>
      <Button
        variant="ghost"
        :disabled="loading"
        @click="load(); loadDates()"
      >
        刷新已有结果
      </Button>
      <RouterLink
        v-if="taskId"
        to="/tasks/runs"
        class="text-muted-foreground underline"
      >
        已提交 {{ taskId }} · 查看任务
      </RouterLink>
    </div>
    <AppApiErrorAlert
      v-if="runError"
      :error="runError"
    />
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <Button
      v-if="error"
      variant="outline"
      @click="load"
    >
      重试数据
    </Button>
    <AppApiErrorAlert
      v-if="datesError"
      :error="datesError"
    />
    <Button
      v-if="datesError"
      variant="outline"
      @click="loadDates"
    >
      重试日期目录
    </Button>
    <Skeleton
      v-if="loading"
      class="h-96 w-full"
    />
    <template v-else-if="data">
      <div
        class="rounded-lg border bg-muted/30 px-4 py-3 text-xs leading-6 text-muted-foreground"
        data-testid="flow-status"
      >
        <span>{{ data.rangeDays === 3 ? '3日榜独立截面' : '1日榜累计' }} · {{ data.dates[0] }} — {{ data.tradeDate }} · {{ flowBoardLabels[data.board] }} · 有效日期 {{ data.dates.length - data.missingDates.length }}/{{ data.dates.length }}</span>
        <span v-if="generatedAt"> · 最近生成 {{ formatDateTime(generatedAt) }}</span>
        <p
          v-if="!filters.endDate && data.expectedTradeDate && data.tradeDate !== data.expectedTradeDate"
          class="text-amber-600 dark:text-amber-400"
        >
          最新快照尚未更新至 {{ data.expectedTradeDate }}，当前为 {{ data.tradeDate }}。
        </p>
        <p v-if="filters.endDate">
          当前查看历史截止日。
        </p>
        <p
          v-if="!data.complete"
          class="text-amber-600 dark:text-amber-400"
        >
          窗口不完整：{{ data.missingDates.join('、') }}。累计线在缺口处停止，区间总额不补零。
        </p>
        <p v-if="data.excludedUndisclosedCount">
          游资视图仅含明确披露游资净额的股票；{{ data.excludedUndisclosedCount }} 条股票日记录未披露，未视为零。
        </p>
        <p v-if="data.sourceQuality.some(q => Object.keys(q.errors).length)">
          部分辅助榜单不可用，详见下方来源质量。
        </p>
      </div>
      <details class="rounded-lg border p-3 text-xs leading-6 text-muted-foreground">
        <summary class="cursor-pointer font-medium text-foreground">
          计算口径与来源质量
        </summary>
        <p>仅表示龙虎榜样本净买入，不是全市场资金流，也不证明同一笔资金在概念之间迁移。金额单位为人民币元，图表以亿元显示。</p>
        <p>股票净额按当日响应中的去重概念等分；尾差按概念排序分配到分，无概念计入“未分类”。Top5占比的分母为所有正净额概念之和，包含未分类。</p>
        <p>机构使用机构榜的机构净额；游资使用全部榜明确披露的股票级游资净额。机构、游资可能重叠，独立展示，不推算“其他”资金。买卖总额仅全部榜可得。</p>
        <p>3日榜仅查看截止日的原始3日榜，不跨日累计。游资席位仅为有限已命名样本，不能用于反推全部游资金额。概念归属为响应观测值，不代表历史成员档案。</p>
        <p class="break-all">
          来源：{{ data.source }} · {{ data.version }}
        </p>
        <div
          v-for="quality in data.sourceQuality"
          :key="quality.tradeDate"
          class="flex flex-wrap gap-x-3"
        >
          <span>{{ quality.tradeDate }} · {{ formatDateTime(quality.generatedAt) }}</span>
          <span>已采集 {{ Object.keys(quality.sources).join(' / ') }}</span>
          <span v-if="Object.keys(quality.errors).length">缺失 {{ Object.keys(quality.errors).join(' / ') }}</span>
        </div>
      </details>
      <div
        class="grid grid-cols-7 gap-3"
        data-testid="flow-summary"
      >
        <Card
          v-for="metric in metrics"
          :key="metric[0]"
        >
          <CardContent class="p-4">
            <p class="text-xs text-muted-foreground">
              {{ metric[0] }}
            </p><p class="mt-2 text-lg font-semibold tabular-nums">
              {{ metric[1] }}
            </p>
          </CardContent>
        </Card>
      </div>
      <div
        v-if="!data.concepts.length"
        class="rounded-lg border p-16 text-center text-muted-foreground"
      >
        {{ data.complete ? (data.excludedUndisclosedCount ? '暂无已披露游资净额的股票记录' : '当前口径无上榜记录') : '暂无完整观察数据，请由管理员在任务中心运行或补数。' }}
      </div>
      <template v-else>
        <div
          class="grid gap-4"
          :class="data.rangeDays === 1 ? 'grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]' : 'grid-cols-1'"
        >
          <Card v-if="data.rangeDays === 1">
            <CardContent class="p-4">
              <h2 class="font-semibold">
                概念累计龙虎榜净额
              </h2>
              <p class="mt-1 text-xs text-muted-foreground">
                窗口起点归零 · 主要正负概念各5个与当前选择 · 点击折线联动
              </p>
              <FlowCharts
                :data="data"
                :selected="selected"
                mode="trajectory"
                @select="selected = $event"
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent class="space-y-3 p-4">
              <h2 class="font-semibold">
                {{ data.rangeDays === 3 ? '3日榜截面' : '区间净流向' }}排行
              </h2>
              <Input
                v-model="search"
                placeholder="搜索概念"
                aria-label="搜索概念"
              />
              <div class="flex items-center gap-1">
                <Button
                  v-for="item in [['all','全部'],['positive','正净额'],['negative','负净额']]"
                  :key="item[0]"
                  size="sm"
                  :variant="direction === item[0] ? 'secondary' : 'ghost'"
                  @click="direction = item[0]!"
                >
                  {{ item[1] }}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  @click="descending = !descending"
                >
                  {{ descending ? '净额降序' : '净额升序' }}
                </Button>
              </div>
              <div
                class="max-h-[25rem] overflow-y-auto"
                data-testid="flow-ranking"
              >
                <button
                  v-for="row in ranking"
                  :key="row.id"
                  class="flex w-full items-center justify-between gap-3 rounded-md border-b px-3 py-3 text-left text-sm hover:bg-muted"
                  :class="selected === row.id ? 'bg-muted font-semibold' : ''"
                  :aria-pressed="selected === row.id"
                  @click="selected = row.id"
                >
                  <span>{{ row.name }}<span class="ml-2 text-xs text-muted-foreground">{{ row.stockCount }}只</span></span><span
                    class="tabular-nums"
                    :class="moneyClass(row.netValue)"
                  >{{ money(row.netValue) }}</span>
                </button>
                <p
                  v-if="!ranking.length"
                  class="p-8 text-center text-sm text-muted-foreground"
                >
                  没有匹配概念
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
        <Card v-if="concept">
          <CardContent class="space-y-4 p-4">
            <h2 class="font-semibold">
              {{ concept.name }} · 资金构成与股票贡献
            </h2>
            <div class="grid grid-cols-3 gap-4 rounded-lg bg-muted/40 p-4 text-sm">
              <p>所选口径净额 <strong :class="moneyClass(concept.netValue)">{{ money(concept.netValue) }}</strong></p>
              <p>机构净额 <strong :class="moneyClass(concept.orgNetValue)">{{ money(concept.orgNetValue) }}</strong></p>
              <p>游资净额 <strong :class="moneyClass(concept.hotMoneyNetValue)">{{ money(concept.hotMoneyNetValue) }}</strong></p>
            </div>
            <p class="text-xs text-muted-foreground">
              分类独立、可能重叠，不构造机构→游资或“其他”路径。以下线宽表示所选口径分摊净额的绝对值。
            </p>
            <FlowCharts
              :data="data"
              :selected="selected"
              :stocks="stocks"
              mode="paths"
              @stock="stock = $event"
            />
            <div class="max-h-96 overflow-auto rounded-md border">
              <table
                class="w-full text-sm"
                data-testid="flow-stocks"
              >
                <thead class="sticky top-0 bg-muted">
                  <tr>
                    <SortableTableHeader
                      label="股票"
                      :active="stockSort === 'name'"
                      :direction="stockDescending ? 'desc' : 'asc'"
                      @sort="sortStocks('name')"
                    /><SortableTableHeader
                      label="所选概念贡献"
                      align="right"
                      :active="stockSort === 'netValue'"
                      :direction="stockDescending ? 'desc' : 'asc'"
                      @sort="sortStocks('netValue')"
                    /><SortableTableHeader
                      label="观察记录"
                      align="right"
                      :active="stockSort === 'days'"
                      :direction="stockDescending ? 'desc' : 'asc'"
                      @sort="sortStocks('days')"
                    />
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in sortedStocks"
                    :key="row.symbol"
                    class="border-t"
                  >
                    <td class="p-3">
                      <Button
                        variant="link"
                        class="h-auto p-0"
                        @click="stock = row.symbol"
                      >
                        {{ row.name }} · {{ row.symbol }}
                      </Button>
                    </td><td
                      class="p-3 text-right tabular-nums"
                      :class="moneyClass(row.netValue)"
                    >
                      {{ money(row.netValue) }}
                    </td><td class="p-3 text-right">
                      {{ row.rows.length }}日
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </template>
    </template>
    <Dialog
      :open="Boolean(stock)"
      @update:open="!$event && (stock = '')"
    >
      <DialogContent
        class="max-h-[85vh] overflow-y-auto sm:max-w-4xl"
        data-testid="flow-stock-dialog"
      >
        <DialogHeader><DialogTitle>{{ stockName }} · {{ stock }}</DialogTitle><DialogDescription>{{ data?.dates[0] }} — {{ data?.tradeDate }} · {{ flowBoardLabels[filters.board] }} · 金额单位亿元</DialogDescription></DialogHeader>
        <p class="text-xs text-muted-foreground">
          股票原始净额与概念贡献分别列示；概念归属按各交易日观测保存。
        </p>
        <table class="w-full text-sm">
          <thead>
            <tr>
              <th class="p-2 text-left">
                日期 / 周期
              </th><th class="p-2 text-right">
                股票整体净额
              </th><th class="p-2 text-right">
                所选口径原始净额
              </th><th class="p-2 text-left">
                当日概念 / 每概念权重
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in stockRows"
              :key="row.tradeDate"
              class="border-t"
            >
              <td class="p-2 whitespace-nowrap">
                {{ row.tradeDate }} / {{ row.rangeDays }}日
              </td><td class="p-2 text-right">
                {{ money(row.stockNetValue) }}
              </td><td class="p-2 text-right">
                {{ money(row.originalNetValue) }}
              </td><td class="p-2">
                {{ row.concepts.join('、') || '未分类' }} · 1/{{ row.allocationCount }}
              </td>
            </tr>
          </tbody>
        </table>
        <h3 class="font-semibold">
          {{ concept?.name }} · 逐日分摊贡献
        </h3>
        <div
          v-for="row in contributions"
          :key="row.tradeDate"
          class="flex justify-between border-b py-2 text-sm"
        >
          <span>{{ row.tradeDate }} · 权重 1/{{ row.allocationCount }}</span>
          <span :class="moneyClass(row.netValue)">{{ money(row.netValue) }}</span>
        </div>
        <h3 class="font-semibold">
          游资明细 · 有限已命名样本
        </h3>
        <p
          v-if="!hotDetails.length"
          class="text-sm text-muted-foreground"
        >
          暂无可用游资明细，不代表游资净额为零。
        </p>
        <div
          v-for="(row, index) in hotDetails"
          :key="index"
          class="flex justify-between border-b py-2 text-sm"
        >
          <span>{{ row.tradeDate }} · {{ row.hotMoneyName }}</span><span :class="moneyClass(row.hotMoneyItemNetValue)">{{ money(row.hotMoneyItemNetValue) }}</span>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>
