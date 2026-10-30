<script setup lang="ts">
import { useMarket } from '@/composables/useMarket';
import { computed, watch } from 'vue';
import { RefreshCw, Layers3 } from 'lucide-vue-next';
import { signalPicks } from '@/components/signal-center/picks';
import StockLink from '@/components/stocks/StockLink.vue';
import { onBeforeUnmount, ref, shallowRef } from 'vue';
import { signalCenterApi as api, type DailySignals, type SignalSummary, type SignalDetail } from '@/api/signalCenter';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import PageHeader from '@/components/layout/PageHeader.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import SignalCard from '@/components/signal-center/SignalCard.vue';
import { horizonText, returnClass } from '@/components/signal-center/evaluation';
import { Button } from '@/components/ui/button';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '@/components/ui/table';
import BilingualEnum from '@/components/app/BilingualEnum.vue';
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';

const { market } = useMarket();
const names = { CN: 'A股', US: '美股' };
const date = ref(''); const loading = ref(false); const offset = ref(0);
const daily = shallowRef<DailySignals | null>(null); const history = shallowRef<SignalSummary[]>([]);
const selected = shallowRef<SignalDetail | null>(null); const open = ref(false); const detailLoading = ref(false);
const error = shallowRef<ParsedApiError | null>(null); const detailError = shallowRef<ParsedApiError | null>(null);
const pickCount = computed(() => daily.value?.items.reduce((count, s) => count + signalPicks(s).length, 0) || 0);
let generation = 0; let detailGeneration = 0;
async function load() {
  const token = ++generation; ++detailGeneration;
  loading.value = true; error.value = null; daily.value = null; history.value = []; open.value = false; selected.value = null;
  try {
    const [today, rows] = await Promise.all([api.daily(date.value || undefined, market.value), api.history(offset.value, market.value)]);
    if (token !== generation) return;
    daily.value = today; history.value = rows;
  } catch (cause) { if (token === generation) error.value = getParsedApiError(cause); }
  finally { if (token === generation) loading.value = false; }
}
async function show(row: SignalSummary) {
  const token = ++detailGeneration; selected.value = null; detailError.value = null; open.value = true; detailLoading.value = true;
  try { const result = await api.detail(row.market, row.signalDate); if (token === detailGeneration) selected.value = result; }
  catch (cause) { if (token === detailGeneration) detailError.value = getParsedApiError(cause); }
  finally { if (token === detailGeneration) detailLoading.value = false; }
}
function page(delta: number) { offset.value = Math.max(0, offset.value + delta); void load(); }
watch(market, () => { date.value = ''; offset.value = 0; void load(); }, { immediate: true });
onBeforeUnmount(() => { ++generation; ++detailGeneration; });
// Signal history uses backend offset pagination without global sort parameters.
</script>

<template>
  <div
    class="space-y-5"
    data-testid="signal-center-page"
  >
    <PageHeader
      variant="section"
      title="信号中心"
      en="Signal Center"
      description="汇聚趋势、ETF、行业与正式共振，逐层审查证据。每个市场精选 0–3 个信号。"
    >
      <template #actions>
        <label
          for="signal-date"
          class="text-sm"
        >交易日期</label>
        <AppDatePicker
          id="signal-date"
          v-model="date"
          disable-weekends
          :clearable="false"
          class="w-44"
          @update:model-value="offset = 0; load()"
        />
        <Button
          variant="outline"
          :disabled="loading"
          @click="date = ''; offset = 0; load()"
        >
          当前市场今天
        </Button>
        <Button
          variant="outline"
          :disabled="loading"
          @click="load"
        >
          <RefreshCw class="mr-1.5 size-3.5" />刷新
        </Button>
      </template>
    </PageHeader>

    <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/20 px-5 py-4">
      <div class="flex items-center gap-3">
        <Layers3 class="size-5 text-muted-foreground" /><div>
          <p class="text-sm font-medium">
            每日研究精选
          </p><p class="mt-1 text-xs text-muted-foreground">
            5 桶初筛 → 最终审查 · 股票与 ETF · 宁缺毋滥
          </p>
        </div>
      </div>
      <div class="flex items-baseline gap-1.5">
        <span class="text-2xl font-semibold tabular-nums">{{ pickCount }}</span><span class="text-xs text-muted-foreground">/ 3 个信号</span>
      </div>
    </div>
    <p class="text-xs text-muted-foreground">
      今天按当前市场当地日期显示；历史分析保持不变，收益随已入库日线更新。
    </p>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <p
      v-if="loading"
      class="text-muted-foreground"
    >
      正在读取信号…
    </p>
    <div
      v-if="daily"
      class="grid min-w-0 grid-cols-1 items-start gap-5"
    >
      <section
        class="min-w-0 rounded-2xl border bg-card p-5 space-y-5 sm:p-6"
      >
        <h2 class="border-b pb-4 text-lg font-semibold">
          {{ names[market] }} · {{ daily.requestedDates[market] }}
        </h2>
        <SignalCard
          v-for="signal in daily.items.filter(s => s.market === market)"
          :key="signal.market"
          :signal="signal"
        />
        <p
          v-if="!daily.items.some(s => s.market === market)"
          class="text-muted-foreground"
        >
          当日尚无信号记录。收盘并完成主要任务后生成。
        </p>
      </section>
    </div>
    <section class="min-w-0 space-y-3 rounded-2xl border bg-card p-4 sm:p-6">
      <h2 class="text-lg font-semibold">
        历史研究记录
      </h2>
      <p class="text-xs text-muted-foreground">
        收益以信号发布后首个交易日开盘为基准，第1日为买入日收盘。未到期与行情缺失分别标注，详情含前10日波动与回撤。
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>
              <IndicatorHelpLabel
                scope="signal"
                label="日期"
                compact
              />
            </TableHead><TableHead>
              <IndicatorHelpLabel
                scope="signal"
                label="市场"
                compact
              />
            </TableHead><TableHead>
              <IndicatorHelpLabel
                scope="signal"
                label="股票"
                compact
              />
            </TableHead>
            <TableHead>
              <IndicatorHelpLabel
                scope="signal"
                label="decision"
                compact
              />
            </TableHead>
            <TableHead>
              <IndicatorHelpLabel
                scope="signal"
                label="confidence"
                compact
              />
            </TableHead><TableHead
              v-for="days in [1, 3, 5, 10]"
              :key="days"
            >
              <IndicatorHelpLabel
                scope="signal"
                :label="`${days}D 收益`"
                compact
              />
            </TableHead><TableHead>
              <IndicatorHelpLabel
                scope="signal"
                label="详情"
                compact
              />
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <template
            v-for="row in history"
            :key="`${row.market}-${row.signalDate}`"
          >
            <TableRow
              v-for="(pick, pickIndex) in (signalPicks(row).length ? signalPicks(row) : [null])"
              :key="pick?.symbol || 'empty'"
            >
              <TableCell class="whitespace-nowrap">
                {{ row.signalDate }}
              </TableCell>
              <TableCell>{{ names[row.market] }}</TableCell>
              <TableCell>
                <StockLink
                  v-if="pick"
                  :code="pick.symbol"
                  :name="pick.name"
                  :market="row.market"
                  :context="{ tradeDate: row.signalDate }"
                />
                <span v-else>—</span>
              </TableCell>
              <TableCell>
                <BilingualEnum
                  v-if="row.decision"
                  :value="row.decision"
                  size="badge"
                /><span v-else>{{ ({ pending: '分析中', failed: '失败', skipped: '跳过', completed: '已完成' } as Record<string, string>)[row.status] }}</span>
              </TableCell>
              <TableCell>{{ ({ high: '高', medium: '中', low: '低' } as Record<string, string>)[pick?.confidence || ''] || '—' }}</TableCell>
              <TableCell
                v-for="days in [1, 3, 5, 10]"
                :key="days"
                :class="returnClass(pick?.evaluation?.horizons.find(h => h.days === days)?.value)"
              >
                {{ pick ? horizonText(pick.evaluation, days) : '—' }}
              </TableCell>
              <TableCell>
                <Button
                  variant="ghost"
                  :aria-label="`查看 ${row.signalDate} ${row.market} 信号${pickIndex ? ` ${pick?.symbol}` : ''}`"
                  @click="show(row)"
                >
                  查看分析
                </Button>
              </TableCell>
            </TableRow>
          </template>
        </TableBody>
      </Table>
      <p
        v-if="!loading && !history.length"
        class="text-sm text-muted-foreground"
      >
        暂无历史记录
      </p>
      <div class="flex gap-2">
        <Button
          variant="outline"
          :disabled="loading || offset === 0"
          @click="page(-50)"
        >
          上一页
        </Button><Button
          variant="outline"
          :disabled="loading || history.length < 50"
          @click="page(50)"
        >
          下一页
        </Button>
      </div>
    </section>
    <Dialog v-model:open="open">
      <DialogContent class="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader><DialogTitle>历史信号分析</DialogTitle><DialogDescription>分析来自当时快照；收益单独使用之后的已入库日线计算。</DialogDescription></DialogHeader>
        <p v-if="detailLoading">
          正在读取历史分析…
        </p><AppApiErrorAlert
          v-if="detailError"
          :error="detailError"
        />
        <SignalCard
          v-if="selected"
          :signal="selected"
        />
      </DialogContent>
    </Dialog>
  </div>
</template>
