<script setup lang="ts">
import { formatFullDateTimeWithTimezone } from '@/utils/format';
import EquityChart from '@/components/paper-trade/EquityChart.vue';
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import { Button } from '@/components/ui/button';
import TradeControlCard from '@/components/paper-trade/TradeControlCard.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { liveTradeApi, type LiveControl, type LiveSnapshot } from '@/api/liveTrade';
import PaperTable, { type Column } from '@/components/paper-trade/PaperTable.vue';
import { contractsApi, type ContractQuote } from '@/api/contracts';

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
const orders = [col('symbol','合约'),col('orderId','订单 ID'),col('side','方向'),col('type','类型'),col('status','状态'),col('price','价格',true),col('origQty','委托数量',true),col('executedQty','成交数量',true),col('time','创建时间',false,true),col('source','来源')];
const algos = [col('symbol','合约'),col('algoId','Algo ID'),col('side','方向'),col('orderType','类型'),col('algoStatus','状态'),col('triggerPrice','触发价',true),col('quantity','数量',true),col('actualOrderId','实际订单 ID'),col('createTime','创建时间',false,true),col('source','来源')];
const trades = [col('symbol','合约'),col('id','成交 ID'),col('orderId','订单 ID'),col('side','方向'),col('positionSide','持仓模式'),col('price','价格',true),col('qty','数量',true),col('commission','手续费',true),col('commissionAsset','费用币种'),col('realizedPnl','已实现盈亏',true),col('time','时间',false,true),col('source','来源')];
const income = [col('symbol','合约'),col('incomeType','流水类型'),col('income','金额',true),col('asset','币种'),col('time','时间',false,true)];
const audit = [col('actor_id','管理员 ID',true),col('previous','变更前'),col('enabled','变更后'),col('changed_at','时间',false,true)];
const contracts = ref(new Map<string, ContractQuote>());

onMounted(() => {
  void contractsApi.snapshot().then(value => { if (!stopped) contracts.value = new Map(value.items.map(row => [row.symbol, row])); }).catch(() => {});
 void refresh(); timer = setInterval(refresh, 10_000); });
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
          实盘交易
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
    <div class="grid items-stretch gap-4 lg:grid-cols-[minmax(16rem,0.8fr)_minmax(0,2fr)]">
      <TradeControlCard
        environment="live"
        heading="自动交易"
        :enabled="control?.enabled ?? false"
        :disabled="loading || updating || control == null"
        :status="switchStatus"
        @change="changeControl"
      >
        <p>策略使用公共行情进行只读观察。开关仅控制 FA 后续自动指令，已有挂单、持仓和 App 手动交易保持独立。</p>
      </TradeControlCard>
      <EquityChart
        :points="snapshot?.equity ?? []"
        unit="USDT / USD"
      />
    </div>
    <p
      v-if="snapshot?.connection.observation"
      class="text-sm text-muted-foreground"
    >
      最近评估 · {{ snapshot.connection.observation.strategy }} · {{ formatFullDateTimeWithTimezone(snapshot.connection.observation.evaluated_at) }}
      · {{ snapshot.connection.observation.direction ?? '暂无信号' }}
    </p>
    <section class="space-y-3 rounded-xl border bg-card p-4 sm:p-5">
      <h2 class="text-lg font-semibold">
        账户概览
        <span class="ml-1 text-xs font-normal text-muted-foreground">USDT / USD</span>
      </h2>
      <div class="flex flex-wrap gap-4 border-t pt-3 text-xs text-muted-foreground">
        <span data-testid="live-connection">账户：{{ connectionStatus }}{{ snapshot?.connection.reason ? ' · ' + snapshot.connection.reason : '' }}</span>
        <span>私有流：{{ snapshot?.connection.stream_connected ? '已连接' : '未连接' }}</span>
        <span>最后同步：{{ formatFullDateTimeWithTimezone(view?.synced_at) }}</span>
        <span>开关更新时间：{{ formatFullDateTimeWithTimezone(control?.updated_at) }}</span>
      </div>
      <p
        v-if="!view?.complete || connectionStatus !== '同步正常'"
        class="text-sm text-muted-foreground"
      >
        完整数据尚未同步，缺失字段显示为 —。旧记录不代表当前账户状态。
      </p>
      <div class="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border md:grid-cols-3 xl:grid-cols-6">
        <div
          v-for="[label, value] in accountValues"
          :key="String(label)"
          class="min-w-0 bg-card px-3 py-4"
        >
          <div class="text-xs text-muted-foreground">
            {{ label }}
          </div>
          <div class="mt-2 break-all text-lg font-semibold tabular-nums">
            {{ value == null ? '—' : String(value) }}
          </div>
        </div>
      </div>
      <h3 class="text-sm font-medium">
        资产余额
      </h3>
      <PaperTable
        :contracts="contracts"
        :rows="view?.balances ?? []"
        :columns="[col('asset','资产'), col('balance','钱包余额',true), col('availableBalance','可用余额',true), col('crossUnPnl','未实现盈亏',true)]"
      />
    </section>
    <section class="space-y-3 rounded-xl border bg-card p-4 sm:p-5">
      <h2 class="text-lg font-semibold">
        当前持仓
      </h2>
      <PaperTable
        :contracts="contracts"
        :rows="view?.positions ?? []"
        :columns="positions"
      />
    </section>
    <section class="space-y-4 rounded-xl border bg-card p-4 sm:p-5">
      <h2 class="text-lg font-semibold">
        当前委托
      </h2>
      <h3 class="text-sm font-medium">
        普通挂单
      </h3>
      <PaperTable
        :contracts="contracts"
        :rows="view?.open_orders ?? []"
        :columns="orders"
      />
      <h3 class="text-sm font-medium">
        条件挂单 (Algo)
      </h3>
      <PaperTable
        :contracts="contracts"
        :rows="view?.open_algos ?? []"
        :columns="algos"
      />
    </section>
    <section class="space-y-4 rounded-xl border bg-card p-4 sm:p-5">
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
        :contracts="contracts"
        :rows="snapshot?.orders ?? []"
        :columns="orders"
      />
      <h3 class="text-sm font-medium">
        条件订单
      </h3>
      <PaperTable
        :contracts="contracts"
        :rows="snapshot?.algos ?? []"
        :columns="algos"
      />
      <h3 class="text-sm font-medium">
        成交明细
      </h3>
      <PaperTable
        :contracts="contracts"
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
        :contracts="contracts"
        :rows="snapshot?.income ?? []"
        :columns="income"
      />
    </section>
    <section class="space-y-3 rounded-xl border bg-card p-4 sm:p-5">
      <h2 class="text-lg font-semibold">
        交易开关变更记录
      </h2>
      <PaperTable
        :contracts="contracts"
        :rows="snapshot?.control_events ?? []"
        :columns="audit"
      />
    </section>
  </div>
</template>
