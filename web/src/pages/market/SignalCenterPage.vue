<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue';
import { signalCenterApi as api, type DailySignals, type SignalSummary, type SignalDetail, type SignalMarket } from '@/api/signalCenter';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import PageHeader from '@/components/layout/PageHeader.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import SignalCard from '@/components/signal-center/SignalCard.vue';
import { horizonText, returnClass } from '@/components/signal-center/evaluation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '@/components/ui/table';

const markets: SignalMarket[] = ['CN', 'US'];
const names = { CN: 'A股', US: '美股' };
const date = ref(''); const loading = ref(false); const offset = ref(0);
const daily = shallowRef<DailySignals | null>(null); const history = shallowRef<SignalSummary[]>([]);
const selected = shallowRef<SignalDetail | null>(null); const open = ref(false); const detailLoading = ref(false);
const error = shallowRef<ParsedApiError | null>(null); const detailError = shallowRef<ParsedApiError | null>(null);
let generation = 0; let detailGeneration = 0;
async function load() {
  const token = ++generation; ++detailGeneration;
  loading.value = true; error.value = null; daily.value = null; history.value = []; open.value = false; selected.value = null;
  try {
    const [today, rows] = await Promise.all([api.daily(date.value || undefined), api.history(offset.value)]);
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
onMounted(() => { void load(); });
onBeforeUnmount(() => { ++generation; ++detailGeneration; });
</script>

<template>
  <div
    class="space-y-5"
    data-testid="signal-center-page"
  >
    <PageHeader
      title="Signal Center"
      description="每日跨信号综合判断。每个市场最多一只 Primary Signal，也可以不交易。"
    />
    <div class="flex items-center gap-3">
      <label
        for="signal-date"
        class="text-sm"
      >交易日期</label>
      <Input
        id="signal-date"
        v-model="date"
        type="date"
        class="w-44"
        @change="load"
      />
      <Button
        variant="outline"
        :disabled="loading"
        @click="date = ''; load()"
      >
        各市场今天
      </Button>
      <Button
        variant="outline"
        :disabled="loading"
        @click="load"
      >
        刷新
      </Button>
      <span class="text-xs text-muted-foreground">今天按各市场当地日期显示；历史分析保持不变，收益随已入库日线更新。</span>
    </div>
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
      class="grid grid-cols-2 gap-5"
    >
      <section
        v-for="market in markets"
        :key="market"
        class="rounded-xl border bg-card p-5 space-y-4"
      >
        <h2 class="text-lg font-semibold">
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
    <section class="space-y-3">
      <h2 class="text-lg font-semibold">
        历史 Signal
      </h2>
      <p class="text-xs text-muted-foreground">
        收益以信号发布后首个交易日开盘为基准，第1日为买入日收盘。未到期与行情缺失分别标注，详情含前10日波动与回撤。
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>日期</TableHead><TableHead>市场</TableHead><TableHead>股票</TableHead><TableHead>Decision</TableHead><TableHead>Confidence</TableHead><TableHead
              v-for="days in [1, 3, 5, 10]"
              :key="days"
            >
              {{ days }}D 收益
            </TableHead><TableHead>详情</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="row in history"
            :key="`${row.market}-${row.signalDate}`"
          >
            <TableCell>{{ row.signalDate }}</TableCell><TableCell>{{ names[row.market] }}</TableCell><TableCell>{{ row.selectedSymbol || '—' }}</TableCell>
            <TableCell>{{ row.decision || ({ pending: '分析中', failed: '失败', skipped: '跳过', completed: '已完成' }[row.status]) }}</TableCell><TableCell>{{ row.confidence || '—' }}</TableCell>
            <TableCell
              v-for="days in [1, 3, 5, 10]"
              :key="days"
              :class="returnClass(row.evaluation?.horizons.find(h => h.days === days)?.value)"
            >
              {{ horizonText(row.evaluation, days) }}
            </TableCell>
            <TableCell>
              <Button
                variant="ghost"
                :aria-label="`查看 ${row.signalDate} ${row.market} 信号`"
                @click="show(row)"
              >
                查看分析
              </Button>
            </TableCell>
          </TableRow>
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
