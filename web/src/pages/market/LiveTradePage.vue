<script setup lang="ts">
import StrategySelect from '@/components/paper-trade/StrategySelect.vue';
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { liveTradeApi, type LiveControl, type LiveSnapshot } from '@/api/liveTrade';
import PaperTable, { type Column } from '@/components/paper-trade/PaperTable.vue';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import { contractsApi, type Candle } from '@/api/contracts';

const snapshot = ref<LiveSnapshot | null>(null);
const control = ref<LiveControl | null>(null);
const loading = ref(false);
const updating = ref(false);
const error = ref<ParsedApiError | null>(null);
const failed = ref(false);
const account = computed(() => snapshot.value?.view?.account ?? {});
const view = computed(() => snapshot.value?.view);
const statusLabels: Record<string, string> = {
  NOT_CONFIGURED: '未配置 Live API', WAITING: '等待后台同步', CONNECTED: '同步正常',
  AUTH_FAILED: '认证失败', SYNC_FAILED: '账户同步失败', UNAVAILABLE: '暂不可用',
};
const connectionStatus = computed(() => failed.value ? '本站连接暂不可用' :
  snapshot.value ? statusLabels[snapshot.value.connection.status] ?? snapshot.value.connection.status : '加载中');
const switchStatus = computed(() => control.value == null ? '交易开关状态未知' : control.value.enabled
  ? '交易已启用 · 只读观察'
  : '自动交易已关闭 · ' + connectionStatus.value);
const accountValues = computed(() => [
  ['账户权益', account.value.totalMarginBalance], ['钱包余额', account.value.totalWalletBalance],
  ['可用余额', account.value.availableBalance], ['保证金占用', account.value.totalInitialMargin],
  ['未实现盈亏', account.value.totalUnrealizedProfit], ['已同步交易净收益', snapshot.value?.realized_net],
]);
let timer: ReturnType<typeof setInterval>;
let stopped = false;
async function refresh() {
  if (loading.value || updating.value || stopped) return;
  loading.value = true;
  try {
    const result = await liveTradeApi.snapshot();
    if (!stopped) { snapshot.value = result; control.value = result.control; failed.value = false; }
  } catch (err) {
    if (!stopped) { error.value = getParsedApiError(err); failed.value = true; control.value = null; }
  } finally { loading.value = false; }
}
async function changeControl(value: boolean) {
  if (updating.value || loading.value || control.value == null) return;
  updating.value = true;
  error.value = null;
  try {
    await liveTradeApi.setControl(value);
    // Read the authoritative persisted state. Never display an optimistic enable.
    const actual = await liveTradeApi.control();
    if (!stopped) control.value = actual;
  } catch (err) {
    if (!stopped) {
      error.value = getParsedApiError(err);
      try { control.value = await liveTradeApi.control(); }
      catch { control.value = null; }
    }
  } finally { updating.value = false; }
  await refresh();
}
function col(key: string, label: string, numeric = false, time = false): Column { return { key, label, numeric, time }; }
const positions = [col('symbol','合约'),col('direction','方向'),col('positionSide','持仓模式'),col('positionAmt','数量',true),col('entryPrice','开仓均价',true),col('markPrice','标记价',true),col('leverage','杠杆',true),col('marginType','保证金模式'),col('positionInitialMargin','保证金',true),col('liquidationPrice','强平价',true),col('unRealizedProfit','未实现盈亏',true),col('fundingRate','资金费率',true),col('source','来源')];
const orders = [col('symbol','合约'),col('orderId','订单 ID'),col('side','方向'),col('type','类型'),col('status','状态'),col('price','价格',true),col('origQty','委托数量',true),col('executedQty','成交数量',true),col('time','创建时间 (UTC)',false,true),col('source','来源')];
const algos = [col('symbol','合约'),col('algoId','Algo ID'),col('side','方向'),col('orderType','类型'),col('algoStatus','状态'),col('triggerPrice','触发价',true),col('quantity','数量',true),col('actualOrderId','实际订单 ID'),col('createTime','创建时间 (UTC)',false,true),col('source','来源')];
const trades = [col('symbol','合约'),col('id','成交 ID'),col('orderId','订单 ID'),col('side','方向'),col('positionSide','持仓模式'),col('price','价格',true),col('qty','数量',true),col('commission','手续费',true),col('commissionAsset','费用币种'),col('realizedPnl','已实现盈亏',true),col('time','时间 (UTC)',false,true),col('source','来源')];
const income = [col('symbol','合约'),col('incomeType','流水类型'),col('income','金额',true),col('asset','币种'),col('time','时间 (UTC)',false,true)];
const audit = [col('actor_id','管理员 ID',true),col('previous','变更前'),col('enabled','变更后'),col('changed_at','时间 (UTC)',false,true)];
const chartSymbol = ref('');
const bars = ref<Candle[]>([]);
let chartGeneration = 0;
async function showChart(symbol: string) {
  chartSymbol.value = symbol;
  bars.value = [];
  const current = ++chartGeneration;
  try {
    const result = await contractsApi.bars(symbol);
    if (!stopped && current === chartGeneration) bars.value = result;
  } catch (err) { if (!stopped) error.value = getParsedApiError(err); }
}
const curve = computed(() => {
  const points = (snapshot.value?.equity ?? []).filter(p => p.equity != null && Number.isFinite(Number(p.equity)));
  if (points.length < 2) return null;
  const prices = points.map(p => Number(p.equity));
  const low = Math.min(...prices), high = Math.max(...prices);
  const start = Date.parse(points[0]!.time), end = Date.parse(points.at(-1)!.time);
  return { low, high, start: points[0]!.time, end: points.at(-1)!.time,
    line: points.map(p => `${10+580*(Date.parse(p.time)-start)/(end-start || 1)},${110-100*(Number(p.equity)-low)/(high-low || 1)}`).join(' ') };
});
onMounted(() => { void refresh(); timer = setInterval(refresh, 10_000); });
onBeforeUnmount(() => { stopped = true; clearInterval(timer); });
</script>

<template>
  <div
    class="space-y-5 py-6"
    data-testid="live-trade-page"
  >
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-3xl font-semibold tracking-tight">
          Live Trade
        </h1>
        <p class="mt-1 text-sm text-muted-foreground">
          Live Trade · Binance USDⓈ-M
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span class="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-1.5 text-sm font-semibold">Binance · LIVE · 真实账户</span>
        <Button
          variant="outline"
          :disabled="loading || updating"
          @click="refresh"
        >
          刷新
        </Button>
      </div>
    </header>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      @dismiss="error = null"
    />
    <StrategySelect environment="live" />
    <p
      v-if="snapshot?.connection.observation"
      class="text-sm text-muted-foreground"
    >
      最近评估 · {{ snapshot.connection.observation.strategy }} · {{ new Date(snapshot.connection.observation.evaluated_at).toLocaleTimeString() }}
      · {{ snapshot.connection.observation.direction ?? '暂无信号' }}
    </p>
    <section class="space-y-4 rounded-lg border p-4">
      <div class="flex flex-wrap justify-between gap-3">
        <div>
          <h2 class="text-lg font-semibold">
            自动交易
          </h2>
          <p
            class="mt-1 text-sm"
            data-testid="live-switch-status"
            role="status"
          >
            {{ switchStatus }}
          </p>
        </div>
        <Switch
          aria-label="自动交易"
          data-testid="live-trading-switch"
          :model-value="control?.enabled ?? false"
          :disabled="loading || updating || control == null"
          @update:model-value="changeControl"
        />
      </div>
      <p class="text-sm text-muted-foreground">
        所选策略使用公共行情进行只读观察。开关只控制 FA 未来的自动交易指令，不冻结 Binance 账户、不撤销现有挂单、不平仓，也不影响 App 手动交易。
      </p>
      <div class="flex flex-wrap gap-4 border-t pt-3 text-xs text-muted-foreground">
        <span data-testid="live-connection">账户：{{ connectionStatus }}{{ snapshot?.connection.reason ? ' · ' + snapshot.connection.reason : '' }}</span>
        <span>私有流：{{ snapshot?.connection.stream_connected ? '已连接' : '未连接' }}</span>
        <span>最后同步 (UTC)：{{ view?.synced_at ?? '—' }}</span>
        <span>开关更新时间：{{ control?.updated_at ?? '—' }}</span>
      </div>
    </section>
    <section class="space-y-3 rounded-lg border p-4">
      <h2 class="text-lg font-semibold">
        账户概览
      </h2>
      <p
        v-if="!view?.complete || connectionStatus !== '同步正常'"
        class="text-sm text-muted-foreground"
      >
        完整数据尚未同步，缺失字段显示为 —。旧记录不代表当前账户状态。
      </p>
      <div class="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <div
          v-for="[label, value] in accountValues"
          :key="String(label)"
          class="min-w-0 rounded-lg border bg-card p-3"
        >
          <div class="text-xs text-muted-foreground">
            {{ label }} (USDT / USD)
          </div>
          <div class="mt-2 break-all text-lg font-semibold tabular-nums">
            {{ value == null ? '—' : String(value) }}
          </div>
        </div>
      </div>
      <div
        v-if="curve"
        class="rounded-md border p-3"
      >
        <h3 class="text-sm font-medium">
          账户权益历史
        </h3>
        <div class="flex justify-between text-xs text-muted-foreground">
          <span>{{ curve.low }}</span><span>{{ curve.high }}</span>
        </div>
        <svg
          viewBox="0 0 600 120"
          role="img"
          aria-label="账户权益变化曲线"
          class="h-32 w-full text-brand"
          preserveAspectRatio="none"
        >
          <polyline
            :points="curve.line"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            vector-effect="non-scaling-stroke"
          />
        </svg>
        <div class="flex justify-between text-xs text-muted-foreground">
          <span>{{ curve.start.slice(0,16) }}</span><span>{{ curve.end.slice(0,16) }}</span>
        </div>
      </div>
      <p
        v-else
        class="text-sm text-muted-foreground"
      >
        权益历史不足，暂不绘制曲线。
      </p>
      <h3 class="text-sm font-medium">
        资产余额
      </h3>
      <PaperTable
        :rows="view?.balances ?? []"
        :columns="[col('asset','资产'), col('balance','钱包余额',true), col('availableBalance','可用余额',true), col('crossUnPnl','未实现盈亏',true)]"
      />
    </section>
    <section class="space-y-3 rounded-lg border p-4">
      <h2 class="text-lg font-semibold">
        当前持仓
      </h2>
      <PaperTable
        :rows="view?.positions ?? []"
        :columns="positions"
        actions
      >
        <template #actions="{ row }">
          <Button
            variant="ghost"
            size="sm"
            @click="showChart(String(row.symbol))"
          >
            查看 K 线
          </Button>
        </template>
      </PaperTable>
      <div
        v-if="chartSymbol"
        class="rounded-md border p-3"
      >
        <div class="flex justify-between">
          <h3>{{ chartSymbol }} · 合约日 K</h3><Button
            variant="ghost"
            size="sm"
            @click="chartSymbol = ''"
          >
            关闭图表
          </Button>
        </div>
        <MarketKLineChart
          v-if="bars.length"
          :symbol="chartSymbol"
          period="1d"
          :bars="bars"
          timezone="UTC"
          disable-forecast
        />
        <p
          v-else
          class="py-8 text-center text-muted-foreground"
        >
          暂无共享行情
        </p>
      </div>
    </section>
    <section class="space-y-4 rounded-lg border p-4">
      <h2 class="text-lg font-semibold">
        当前委托
      </h2>
      <h3 class="text-sm font-medium">
        普通挂单
      </h3>
      <PaperTable
        :rows="view?.open_orders ?? []"
        :columns="orders"
      />
      <h3 class="text-sm font-medium">
        条件挂单 (Algo)
      </h3>
      <PaperTable
        :rows="view?.open_algos ?? []"
        :columns="algos"
      />
    </section>
    <section class="space-y-4 rounded-lg border p-4">
      <h2 class="text-lg font-semibold">
        历史订单与成交
      </h2>
      <p class="text-sm text-muted-foreground">
        首版所有记录均来自 Binance App / 网站或其他外部来源，不归属 FA 实盘策略。
      </p>
      <h3 class="text-sm font-medium">
        普通订单
      </h3>
      <PaperTable
        :rows="snapshot?.orders ?? []"
        :columns="orders"
      />
      <h3 class="text-sm font-medium">
        条件订单
      </h3>
      <PaperTable
        :rows="snapshot?.algos ?? []"
        :columns="algos"
      />
      <h3 class="text-sm font-medium">
        成交明细
      </h3>
      <PaperTable
        :rows="snapshot?.trades ?? []"
        :columns="trades"
      />
      <h3 class="text-sm font-medium">
        资金流水
      </h3>
      <p class="text-xs text-muted-foreground">
        交易净收益仅汇总已同步 USDT 已实现盈亏、手续费及资金费，不计资金划转。
      </p>
      <PaperTable
        :rows="snapshot?.income ?? []"
        :columns="income"
      />
    </section>
    <section class="space-y-3 rounded-lg border p-4">
      <h2 class="text-lg font-semibold">
        交易开关变更记录
      </h2>
      <PaperTable
        :rows="snapshot?.control_events ?? []"
        :columns="audit"
      />
    </section>
  </div>
</template>
