<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import { Button } from '@/components/ui/button';
import TradeControlCard from '@/components/paper-trade/TradeControlCard.vue';
import EquityChart from '@/components/paper-trade/EquityChart.vue';
import AppConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { paperTradeApi, type PaperSnapshot, type Row } from '@/api/paperTrade';
import PaperTable, { type Column } from '@/components/paper-trade/PaperTable.vue';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import { contractsApi, type Candle } from '@/api/contracts';

const data = ref<PaperSnapshot | null>(null);
const busy = ref(false);
const loadFailed = ref(false);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const notice = ref('');
const marketStatus = ref('等待行情');
const globalEnabled = computed(() => data.value?.trade_control?.enabled === true);
const connected = computed(() => !loadFailed.value && data.value?.connection.status === 'CONNECTED' && data.value.view?.complete);
const view = computed(() => data.value?.view);
const account = computed(() => view.value?.account ?? {});
const statuses: Record<string, string> = {
  NOT_CONFIGURED: '未配置 Demo API', WAITING: '等待后台同步',
  CONNECTED: '连接正常', AUTH_FAILED: '账户认证失败', UNAVAILABLE: '暂不可用', DEGRADED: '部分能力不可用（只读）',
};
const kpis = computed(() => [
  ['账户权益', account.value.totalMarginBalance], ['钱包余额', account.value.totalWalletBalance],
  ['可用余额', account.value.availableBalance], ['保证金占用', account.value.totalInitialMargin],
  ['未实现盈亏', account.value.totalUnrealizedProfit], ['已同步净收益', data.value?.realized_net],
]);
const pending = ref<{ title: string; description: string; run: () => Promise<unknown> } | null>(null);
const dialogOpen = ref(false);
let timer: ReturnType<typeof setInterval>;
let stopped = false;
let refreshGeneration = 0;
async function refreshMarket() {
  try {
    const market = await contractsApi.snapshot();
    if (stopped) return;
    marketStatus.value = market.items.some(row => row.quote && Math.abs(Date.now() - row.quote.timestamp) < 60_000)
      ? '有实时行情' : '行情缺失或延迟';
  } catch { if (!stopped) marketStatus.value = '行情暂不可用'; }
}
async function refresh(force = false) {
  if (stopped || (!force && (loading.value || busy.value))) return;
  const generation = ++refreshGeneration;
  loading.value = true;
  void refreshMarket();
  try {
    const result = await paperTradeApi.snapshot();
    if (!stopped && generation === refreshGeneration) { data.value = result; loadFailed.value = false; }
  } catch (err) { if (!stopped && generation === refreshGeneration) { error.value = getParsedApiError(err); loadFailed.value = true; } }
  finally { if (generation === refreshGeneration) loading.value = false; }
}
async function mutate(run: () => Promise<unknown>, message: string) {
  if (busy.value) return;
  busy.value = true;
  error.value = null;
  notice.value = '';
  try { await run(); notice.value = message; await refresh(true); }
  catch (err) { error.value = getParsedApiError(err); await refresh(true); }
  finally { busy.value = false; }
}
function confirm(title: string, description: string, run: () => Promise<unknown>) {
  pending.value = { title, description, run };
  dialogOpen.value = true;
}
async function execute() {
  const action = pending.value;
  dialogOpen.value = false;
  if (action) await mutate(action.run, '已提交请求，请等待 Demo 交易所核对；不代表已成交。');
}
function closePosition(row: Row) {
  const payload = { request_id: crypto.randomUUID(), confirm_demo: true, symbol: row.symbol, position_side: row.positionSide, expected_quantity: row.positionAmt, expected_entry_price: row.entryPrice ?? null };
  confirm('确认 Demo 平仓', `对 ${row.symbol} 当前数量 ${row.positionAmt} 提交仅减仓市价单；FA 策略仓位将暂停自动开仓。`, () => paperTradeApi.action('close', payload));
}
function cancelOrder(row: Row, algo: boolean) {
  const payload = { request_id: crypto.randomUUID(), confirm_demo: true, symbol: row.symbol, exchange_id: String(algo ? row.algoId : row.orderId), algo };
  confirm('确认撤销 Demo 委托', `${row.symbol} · ${payload.exchange_id}。撤销保护单不会自动平仓。`, () => paperTradeApi.action('cancel', payload));
}
async function changeTradeControl(enabled: boolean) {
  if (busy.value || loading.value || !data.value) return;
  await mutate(async () => {
    await paperTradeApi.setTradeControl(enabled);
    const actual = await paperTradeApi.tradeControl();
    if (data.value) data.value = { ...data.value, trade_control: actual };
  }, enabled ? '已启用 Demo 新增仓位。' : '已禁止 Demo 新增仓位；账户同步、撤单、平仓及已有保护单管理继续。');
}
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
  } catch (err) { error.value = getParsedApiError(err); }
}
function column(key: string, label: string, numeric = false, time = false): Column { return { key, label, numeric, time }; }
const positions = [column('symbol','合约'), column('direction','方向'), column('positionSide','持仓模式'), column('positionAmt','数量（正多负空）',true), column('entryPrice','开仓均价',true), column('markPrice','标记价',true), column('leverage','杠杆',true), column('marginType','保证金模式'), column('positionInitialMargin','保证金',true), column('liquidationPrice','强平价',true),column('fundingRate','Demo 资金费率',true), column('unRealizedProfit','未实现盈亏',true), column('source','归属')];
const orders = [column('symbol','合约'),column('orderId','订单 ID'),column('side','方向'),column('type','类型'),column('status','状态'),column('price','价格',true),column('origQty','委托数量',true),column('executedQty','成交数量',true),column('time','时间 (UTC)',false,true),column('source','来源')];
const algos = [column('symbol','合约'),column('algoId','Algo ID'),column('side','方向'),column('orderType','类型'),column('algoStatus','状态'),column('triggerPrice','触发价',true),column('quantity','数量',true),column('actualOrderId','实际订单 ID'),column('createTime','时间 (UTC)',false,true),column('source','来源')];
const trades = [column('symbol','合约'),column('id','成交 ID'),column('orderId','订单 ID'),column('side','方向'),column('price','价格',true),column('qty','数量',true),column('realizedPnl','已实现盈亏',true),column('commission','手续费',true),column('commissionAsset','手续费币种'),column('time','时间 (UTC)',false,true),column('source','归属'),column('intent_action','开平仓意图'),column('strategy_type','开仓策略类型'),column('net_excluding_funding','净收益（不含资金费）',true)];
const income = [column('symbol','合约'),column('incomeType','流水类型'),column('income','金额',true),column('asset','币种'),column('time','时间 (UTC)',false,true)];
const intents = [column('symbol','合约'),column('strategy','策略'),column('action','意图'),column('payload.strategy_type','策略类型'),column('payload.direction','信号方向'),column('bar_time','闭合时间 (UTC)',false,true),column('payload.fast_ema','快 EMA',true),column('payload.slow_ema','慢 EMA',true),column('payload.anchor','驱动窗口 (UTC)',false,true),column('payload.range_pct','振幅 (%)',true),column('payload.move_pct','方向涨跌幅 (%)',true),column('payload.efficiency','路径效率',true),column('payload.ratchet_stage','棘轮档位',true),column('payload.exit_reason','退出原因'),column('status','执行状态'),column('reason','原因'),column('created_at','创建时间 (UTC)',false,true)];
const openOrder = (row: Row) => ['NEW', 'PARTIALLY_FILLED'].includes(String(row.status)) &&
  view.value?.open_orders?.some(order => String(order.orderId) === String(row.orderId) && order.symbol === row.symbol);
const openAlgo = (row: Row) => row.algoStatus === 'NEW' &&
  view.value?.open_algos?.some(order => String(order.algoId) === String(row.algoId) && order.symbol === row.symbol);
onMounted(() => { void refresh(); timer = setInterval(() => { void refresh(); }, 10_000); });
onBeforeUnmount(() => { stopped = true; clearInterval(timer); });
</script>

<template>
  <div
    class="space-y-5 py-6"
    data-testid="paper-trade-page"
  >
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-3xl font-semibold tracking-tight">
          模拟交易
        </h1>
        <p class="mt-1 text-sm text-muted-foreground">
          Paper Trade · Binance USDⓈ-M Demo Trading
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span class="rounded-md border border-brand/40 bg-brand/10 px-3 py-1.5 text-sm font-semibold">仅 Binance Demo</span>
        <Button
          variant="outline"
          :disabled="loading"
          @click="refresh()"
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
    <p
      v-if="notice"
      class="rounded-lg border bg-muted/40 p-3 text-sm"
      role="status"
    >
      {{ notice }}
    </p>
    <div class="grid items-stretch gap-4 lg:grid-cols-[minmax(16rem,0.8fr)_minmax(0,2fr)]">
      <TradeControlCard
        environment="paper"
        heading="Demo 交易总开关"
        :enabled="globalEnabled"
        :disabled="busy || loading || !data || loadFailed || (!globalEnabled && !connected)"
        :status="!data || loadFailed ? '开关状态未知' : globalEnabled ? '新增仓位已启用' : '新增仓位已关闭'"
        @change="changeTradeControl"
      >
        <p>关闭后仍同步模拟账户。已有保护单、撤单、平仓及风险管理继续运行。</p>
      </TradeControlCard>
      <EquityChart
        :points="data?.equity ?? []"
        unit="USDT"
      />
    </div>
    <section class="space-y-4 rounded-xl border bg-card p-4 sm:p-5">
      <div class="flex flex-wrap justify-between gap-3">
        <h2 class="text-lg font-semibold">
          账户总览
          <span class="ml-1 text-xs font-normal text-muted-foreground">USDT</span>
        </h2>
        <div
          class="text-sm text-muted-foreground"
          role="status"
          data-testid="demo-connection"
        >
          {{ loadFailed ? '本站连接暂不可用' : data ? (statuses[data.connection.status] ?? data.connection.status) : '加载中' }}{{ data?.connection.reason ? ' · ' + data.connection.reason : '' }} · 私有流：{{ data?.connection.stream_connected ? '已连接' : '未连接（REST 核对）' }}
        </div>
      </div>
      <p class="text-xs text-muted-foreground">
        最后同步 (UTC)：{{ view?.synced_at ?? '—' }} · {{ view?.complete ? '已完成订单及账户核对' : '尚未完成完整核对' }} · 生产行情：{{ marketStatus }}（独立于 Demo）
      </p>
      <div class="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border md:grid-cols-3 xl:grid-cols-6">
        <div
          v-for="[label, value] in kpis"
          :key="String(label)"
          class="min-w-0 bg-card px-3 py-4"
        >
          <div class="text-xs text-muted-foreground">
            {{ label }}
          </div>
          <div class="mt-2 break-all text-lg font-semibold tabular-nums">
            {{ value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(2) }}
          </div>
        </div>
      </div>
    </section>
    <section class="space-y-3 rounded-xl border bg-card p-4 sm:p-5">
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
            size="sm"
            variant="ghost"
            @click="showChart(String(row.symbol))"
          >
            K 线
          </Button>
          <Button
            size="sm"
            variant="outline"
            :disabled="!connected || busy || row.positionSide !== 'BOTH'"
            @click="closePosition(row)"
          >
            平仓
          </Button>
        </template>
      </PaperTable>
      <div
        v-if="chartSymbol"
        class="rounded-md border p-3"
      >
        <div class="flex justify-between">
          <h3>{{ chartSymbol }} · 生产市场日 K（研究输入）</h3><Button
            size="sm"
            variant="ghost"
            @click="chartSymbol = ''"
          >
            关闭
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

    <section class="space-y-4 rounded-xl border bg-card p-4 sm:p-5">
      <h2 class="text-lg font-semibold">
        委托及订单
      </h2>
      <h3 class="text-sm font-medium">
        普通订单
      </h3>
      <PaperTable
        :rows="data?.orders ?? []"
        :columns="orders"
        actions
      >
        <template #actions="{ row }">
          <Button
            v-if="openOrder(row)"
            variant="outline"
            size="sm"
            :disabled="!connected || busy"
            @click="cancelOrder(row, false)"
          >
            撤单
          </Button>
        </template>
      </PaperTable>
      <h3 class="text-sm font-medium">
        条件订单 (Algo)
      </h3>
      <PaperTable
        :rows="data?.algos ?? []"
        :columns="algos"
        actions
      >
        <template #actions="{ row }">
          <Button
            v-if="openAlgo(row)"
            variant="outline"
            size="sm"
            :disabled="!connected || busy"
            @click="cancelOrder(row, true)"
          >
            撤单
          </Button>
        </template>
      </PaperTable>
    </section>
    <section class="space-y-4 rounded-xl border bg-card p-4 sm:p-5">
      <h2 class="text-lg font-semibold">
        成交历史与资金流水
      </h2>
      <PaperTable
        :rows="data?.trades ?? []"
        :columns="trades"
      />
      <h3 class="text-sm font-medium">
        资金流水（含资金费、手续费与已实现盈亏）
      </h3>
      <PaperTable
        :rows="data?.income ?? []"
        :columns="income"
      />
    </section>
    <section class="space-y-3 rounded-xl border bg-card p-4 sm:p-5">
      <h2 class="text-lg font-semibold">
        信号与执行日志
      </h2>
      <PaperTable
        :rows="data?.intents ?? []"
        :columns="intents"
      />
    </section>
    <AppConfirmDialog
      v-model:open="dialogOpen"
      :title="pending?.title ?? ''"
      :description="pending?.description ?? ''"
      confirm-text="确认提交"
      @confirm="execute"
    />
  </div>
</template>
