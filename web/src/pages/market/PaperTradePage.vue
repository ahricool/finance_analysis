<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import FieldInput from '@/components/forms/FieldInput.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
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
const symbols = computed(() => (view.value?.demo_symbols ?? []).map(value => ({ value, label: value })));
const strategySymbols = computed(() => symbols.value.filter(s => view.value?.shared_symbols?.includes(s.value)));
const manual = reactive({ symbol: '', side: '', order_type: '', quantity: '', price: '', trigger_price: '', reduce_only: false });
let manualSubmission: { fingerprint: string; id: string } | null = null;
const strategy = reactive({ symbol: '', name: '', strategy_type: 'ema_cross', fast: '9', slow: '21', direction: 'LONG',
  notional: '', margin: '', max_position: '', leverage_limit: '', max_loss: '', stop_pct: '' });
const sideOptions = [{ value: 'BUY', label: 'BUY · 买入' }, { value: 'SELL', label: 'SELL · 卖出' }];
const typeOptions = ['MARKET', 'LIMIT', 'STOP_MARKET', 'TAKE_PROFIT_MARKET'].map(value => ({ value, label: value }));
const strategyFields = [
  ['name', '策略名称'], ['fast', '快 EMA'], ['slow', '慢 EMA'], ['notional', '计划名义额度 (USDT)'],
  ['margin', '计划保证金 (USDT)'], ['max_position', '最大名义持仓 (USDT)'], ['leverage_limit', '杠杆上限'],
  ['max_loss', '最大亏损 (USDT)'], ['stop_pct', '止损比例 (%)'],
] as const;
const manualValid = computed(() => !!manual.symbol && !!manual.side && !!manual.order_type && Number(manual.quantity) > 0 &&
  (manual.order_type !== 'LIMIT' || Number(manual.price) > 0) &&
  (!['STOP_MARKET', 'TAKE_PROFIT_MARKET'].includes(manual.order_type) || Number(manual.trigger_price) > 0));
const strategyValid = computed(() => !!strategy.symbol && !!strategy.name && strategyFields.slice(1).every(([key]) => Number(strategy[key]) > 0));
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
function submitManual() {
  const fields = { ...manual,
    price: manual.order_type === 'LIMIT' ? manual.price : null,
    trigger_price: ['STOP_MARKET', 'TAKE_PROFIT_MARKET'].includes(manual.order_type) ? manual.trigger_price : null };
  const fingerprint = JSON.stringify(fields);
  if (manualSubmission?.fingerprint !== fingerprint) manualSubmission = { fingerprint, id: crypto.randomUUID() };
  const payload = { request_id: manualSubmission.id, confirm_demo: true, ...fields };
  confirm('确认 Binance Demo 模拟委托', `${payload.symbol} · ${payload.side} · ${payload.order_type} · 数量 ${payload.quantity}${payload.price ? ' · 价格 ' + payload.price : ''}${payload.trigger_price ? ' · 触发价 ' + payload.trigger_price : ''}${payload.reduce_only ? ' · 仅减仓' : ''}。由币安模拟交易所处理。`, async () => {
    await paperTradeApi.action('orders', payload);
    manualSubmission = null;
    Object.assign(manual, { symbol: '', side: '', order_type: '', quantity: '', price: '', trigger_price: '', reduce_only: false });
  });
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
function saveStrategy() {
  const payload = { ...strategy };
  void mutate(() => paperTradeApi.saveStrategy(payload.symbol, payload), '策略已保存（默认暂停）。');
}
function editStrategy(row: Row) {
  for (const key of Object.keys(strategy) as (keyof typeof strategy)[]) if (row[key] != null) strategy[key] = String(row[key]);
}
function control(row: Row) {
  const enabled = !row.enabled;
  if (enabled) confirm('启用自动 Demo 策略', `${row.symbol} 将根据闭合 5 分钟 K 线，在所配置额度及风险限制内自动向 Binance Demo 提交订单，关闭页面后仍运行。`, () => paperTradeApi.control(String(row.symbol), true));
  else void mutate(() => paperTradeApi.control(String(row.symbol), false), '已暂停新增仓位；现有保护单保留。');
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
const curve = computed(() => {
  const points = (data.value?.equity ?? []).filter(p => p.equity != null && Number.isFinite(Number(p.equity)));
  if (points.length < 2) return null;
  const values = points.map(p => Number(p.equity));
  const min = Math.min(...values), max = Math.max(...values);
  const start = Date.parse(points[0]!.time), end = Date.parse(points.at(-1)!.time);
  return { min, max, start: points[0]!.time, end: points.at(-1)!.time,
    line: points.map(p => `${10 + 580 * (Date.parse(p.time) - start) / (end - start || 1)},${110 - 100 * (Number(p.equity) - min) / (max - min || 1)}`).join(' ') };
});
function column(key: string, label: string, numeric = false, time = false): Column { return { key, label, numeric, time }; }
const positions = [column('symbol','合约'), column('direction','方向'), column('positionSide','持仓模式'), column('positionAmt','数量（正多负空）',true), column('entryPrice','开仓均价',true), column('markPrice','标记价',true), column('leverage','杠杆',true), column('marginType','保证金模式'), column('positionInitialMargin','保证金',true), column('liquidationPrice','强平价',true),column('fundingRate','Demo 资金费率',true), column('unRealizedProfit','未实现盈亏',true), column('source','归属')];
const strategies = [column('symbol','合约'),column('name','名称'),column('enabled','自动执行'),column('status','状态'),column('fast','快 EMA',true),column('slow','慢 EMA',true),column('direction','方向'),column('notional','计划额度',true),column('margin','保证金',true),column('current_leverage','Demo 杠杆',true),column('current_margin_type','Demo 保证金模式'),column('leverage_limit','杠杆上限',true),column('max_position','最大持仓',true),column('max_loss','最大亏损',true),column('stop_pct','止损 (%)',true),column('latest_signal.payload.direction','最近信号'),column('latest_signal.status','执行状态'),column('latest_signal.reason','原因'), column('latest_trade.time','最近成交 (UTC)',false,true)];
const stats = [column('name','策略'), column('symbol','合约'), column('performance.trades','交易次数',true),column('performance.win_rate_pct','胜率 (%)',true),column('performance.average_hold_minutes','平均持仓 (分钟)',true),column('performance.net','累计净收益',true),column('performance.max_drawdown','已结算最大回撤 (USDT)',true)];
const orders = [column('symbol','合约'),column('orderId','订单 ID'),column('side','方向'),column('type','类型'),column('status','状态'),column('price','价格',true),column('origQty','委托数量',true),column('executedQty','成交数量',true),column('time','时间 (UTC)',false,true),column('source','来源')];
const algos = [column('symbol','合约'),column('algoId','Algo ID'),column('side','方向'),column('orderType','类型'),column('algoStatus','状态'),column('triggerPrice','触发价',true),column('quantity','数量',true),column('actualOrderId','实际订单 ID'),column('createTime','时间 (UTC)',false,true),column('source','来源')];
const trades = [column('symbol','合约'),column('id','成交 ID'),column('orderId','订单 ID'),column('side','方向'),column('price','价格',true),column('qty','数量',true),column('realizedPnl','已实现盈亏',true),column('commission','手续费',true),column('commissionAsset','手续费币种'),column('time','时间 (UTC)',false,true),column('source','归属'),column('intent_action','开平仓意图'),column('net_excluding_funding','净收益（不含资金费）',true)];
const income = [column('symbol','合约'),column('incomeType','流水类型'),column('income','金额',true),column('asset','币种'),column('time','时间 (UTC)',false,true)];
const intents = [column('symbol','合约'),column('strategy','策略'),column('action','意图'),column('payload.direction','信号方向'),column('bar_time','闭合时间 (UTC)',false,true),column('payload.fast_ema','快 EMA',true),column('payload.slow_ema','慢 EMA',true),column('status','执行状态'),column('reason','原因'),column('created_at','创建时间 (UTC)',false,true)];
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
    <section class="space-y-2 rounded-lg border p-4">
      <div class="flex flex-wrap justify-between gap-3">
        <div>
          <h2 class="text-lg font-semibold">
            Demo 交易总开关
          </h2>
          <p class="text-sm text-muted-foreground">
            {{ globalEnabled ? '新增仓位已启用' : '新增仓位已关闭' }}
          </p>
        </div>
        <Switch
          data-testid="paper-trading-switch"
          aria-label="Demo 交易总开关"
          :model-value="globalEnabled"
          :disabled="busy || loading || !data || loadFailed || (!globalEnabled && !connected)"
          @update:model-value="changeTradeControl"
        />
      </div>
      <p class="text-sm text-muted-foreground">
        关闭时继续账户同步，禁止 FA 新增仓位；已有保护单、撤单、平仓及风险管理不受影响。仅作用于 Binance Demo，不影响实盘开关。
      </p>
    </section>
    <section class="space-y-4 rounded-lg border p-4">
      <div class="flex flex-wrap justify-between gap-3">
        <h2 class="text-lg font-semibold">
          账户总览
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
      <div class="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <div
          v-for="[label, value] in kpis"
          :key="String(label)"
          class="min-w-0 rounded-lg border bg-card p-3"
        >
          <div class="text-xs text-muted-foreground">
            {{ label }} (USDT)
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
          账户权益曲线
        </h3>
        <div class="flex justify-between text-xs text-muted-foreground">
          <span>{{ curve.min }}</span><span>{{ curve.max }} USDT</span>
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
          <span>{{ curve.start.slice(0, 16) }}</span><span>{{ curve.end.slice(0, 16) }}</span>
        </div>
      </div>
      <p
        v-else
        class="text-sm text-muted-foreground"
      >
        权益历史不足，暂不绘制曲线。
      </p>
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
    <section class="space-y-4 rounded-lg border p-4">
      <h2 class="text-lg font-semibold">
        策略与控制
      </h2>
      <p class="text-sm text-muted-foreground">
        EMA 交叉仅用于验证模拟交易闭环。保存后默认暂停，可观察信号；启用后才自动开仓。
      </p>
      <PaperTable
        :rows="data?.strategies ?? []"
        :columns="strategies"
        actions
      >
        <template #actions="{ row }">
          <Button
            size="sm"
            variant="ghost"
            :disabled="!!row.enabled"
            @click="editStrategy(row)"
          >
            编辑
          </Button>
          <Button
            size="sm"
            variant="outline"
            :disabled="busy || (!row.enabled && !connected)"
            @click="control(row)"
          >
            {{ row.enabled ? '暂停' : '启用' }}
          </Button>
        </template>
      </PaperTable>
      <form
        class="grid grid-cols-2 gap-3 rounded-lg border p-3 md:grid-cols-3 xl:grid-cols-4"
        @submit.prevent="saveStrategy"
      >
        <FieldSelect
          v-model="strategy.symbol"
          label="策略合约"
          :options="strategySymbols"
        />
        <FieldSelect
          v-model="strategy.direction"
          label="允许方向"
          :options="[{ value:'LONG', label:'只做多' },{value:'BOTH',label:'双向'}]"
        />
        <FieldInput
          v-for="[key,label] in strategyFields"
          :key="key"
          v-model="strategy[key]"
          :label="label"
        />
        <div class="flex items-end">
          <Button
            type="submit"
            :disabled="!strategyValid || busy"
          >
            保存策略
          </Button>
        </div>
      </form>
      <h3 class="font-medium">
        策略绩效（可归属的已结算往返交易）
      </h3>
      <PaperTable
        :rows="data?.strategies ?? []"
        :columns="stats"
      />
    </section>
    <section class="space-y-4 rounded-lg border p-4">
      <h2 class="text-lg font-semibold">
        手动模拟验证
      </h2>
      <p class="text-sm text-muted-foreground">
        请自行选定合约、方向、委托类型与数量。订单只提交至 Binance Demo，不会自动预填交易指令。
      </p>
      <form
        class="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4"
        @submit.prevent="submitManual"
      >
        <FieldSelect
          v-model="manual.symbol"
          label="Demo 合约"
          :options="symbols"
        />
        <FieldSelect
          v-model="manual.side"
          label="方向"
          :options="sideOptions"
        />
        <FieldSelect
          v-model="manual.order_type"
          label="订单类型"
          :options="typeOptions"
        />
        <FieldInput
          v-model="manual.quantity"
          label="数量"
          data-testid="demo-quantity"
        />
        <FieldInput
          v-if="manual.order_type === 'LIMIT'"
          v-model="manual.price"
          label="限价"
        />
        <FieldInput
          v-if="['STOP_MARKET','TAKE_PROFIT_MARKET'].includes(manual.order_type)"
          v-model="manual.trigger_price"
          label="触发价"
        />
        <label class="flex items-center gap-2 text-sm"><input
          v-model="manual.reduce_only"
          type="checkbox"
        >仅减仓</label>
        <div class="flex items-end">
          <Button
            type="submit"
            :disabled="!connected || (!globalEnabled && !manual.reduce_only) || !manualValid || busy"
          >
            核对模拟委托
          </Button>
        </div>
      </form>
    </section>
    <section class="space-y-4 rounded-lg border p-4">
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
    <section class="space-y-4 rounded-lg border p-4">
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
    <section class="space-y-3 rounded-lg border p-4">
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
