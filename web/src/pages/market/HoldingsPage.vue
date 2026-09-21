<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import {
  holdingsApi,
  tradeEngineApi,
  type PortfolioAccount,
  type PortfolioPosition,
  type TradeEnginePosition,
} from '@/api/holdings';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import DailyKLineCard from '@/components/market-data/DailyKLineCard.vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { TradeMarker } from '@/lib/tradeMarkers';
import { computed, onMounted, ref } from 'vue';

const market = ref<'CN' | 'US'>('CN');
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const accounts = ref<PortfolioAccount[]>([]);
const positions = ref<PortfolioPosition[]>([]);
const cash = ref('0');
const marketValue = ref('0');
const totalAsset = ref('0');
const exposure = ref<string | null>(null);
const engine = ref<TradeEnginePosition[]>([]);
const formOpen = ref(false);
const formKind = ref<'buy' | 'sell' | 'deposit' | 'withdraw'>('buy');
const formSymbol = ref('');
const formQuantity = ref('');
const formPrice = ref('');
const formAmount = ref('');
const formPositionId = ref<number | null>(null);
const saving = ref(false);
const detail = ref<PortfolioPosition | null>(null);
const operations = ref<Array<{ executedAt: string; side: string; quantity: string; price: string }>>([]);
const markers = ref<TradeMarker[]>([]);
const account = computed(() => accounts.value[0] || null);

onMounted(() => {
  void load();
});
const engineBySymbol = computed(() => Object.fromEntries(engine.value.map(item => [item.symbol, item])));
const engineView = computed(() => {
  if (!detail.value) return null;
  return (
    engine.value.find(item => item.positionId === String(detail.value?.id)) ||
    engineBySymbol.value[detail.value.symbol] ||
    null
  );
});

function fmt(value?: string | null) {
  if (value == null || value === '') return '-';
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString(undefined, { maximumFractionDigits: 4 }) : value;
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const [summary, views] = await Promise.all([
      holdingsApi.summary(market.value),
      tradeEngineApi.positions(market.value).catch(() => []),
    ]);
    accounts.value = summary.accounts;
    positions.value = summary.positions;
    cash.value = summary.cash;
    marketValue.value = summary.marketValue;
    totalAsset.value = summary.totalAsset;
    exposure.value = summary.grossExposure;
    engine.value = views;
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    loading.value = false;
  }
}

function openForm(kind: typeof formKind.value, row?: PortfolioPosition) {
  formKind.value = kind;
  formSymbol.value = row?.symbol || '';
  formQuantity.value = '';
  formPrice.value = row?.currentPrice || '';
  formAmount.value = '';
  formPositionId.value = row?.id ?? null;
  formOpen.value = true;
}

async function submitForm() {
  if (!account.value) return;
  saving.value = true;
  error.value = null;
  try {
    if (formKind.value === 'deposit') await holdingsApi.deposit({ accountId: account.value.id, amount: formAmount.value });
    else if (formKind.value === 'withdraw') await holdingsApi.withdraw({ accountId: account.value.id, amount: formAmount.value });
    else if (formKind.value === 'buy') {
      await holdingsApi.buy({ accountId: account.value.id, symbol: formSymbol.value, quantity: formQuantity.value, price: formPrice.value });
    } else if (formPositionId.value != null) {
      await holdingsApi.sell({ positionId: formPositionId.value, quantity: formQuantity.value, price: formPrice.value });
    }
    formOpen.value = false;
    await load();
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    saving.value = false;
  }
}

async function openDetail(row: PortfolioPosition) {
  detail.value = row;
  const [ops, marks] = await Promise.all([holdingsApi.operations(row.id), holdingsApi.markers(row.id)]);
  operations.value = ops;
  markers.value = marks.map(item => ({
    timestamp: Date.parse(item.timestamp),
    type: item.type,
    operations: item.operations.map(op => ({ executedAt: op.executedAt, side: op.side, quantity: op.quantity, price: op.price })),
  }));
}

async function toggleTradeEngine(enabled: boolean) {
  if (!detail.value) return;
  error.value = null;
  try {
    const updated = await holdingsApi.updatePosition(detail.value.id, { tradeEngineEnabled: enabled });
    detail.value = { ...detail.value, tradeEngineEnabled: updated.tradeEngineEnabled };
    await load();
    const refreshed = positions.value.find(item => item.id === detail.value?.id);
    if (refreshed) detail.value = { ...detail.value, ...refreshed };
  } catch (err) {
    error.value = getParsedApiError(err);
  }
}

function onTradeEngineChange(event: Event) {
  const target = event.target as HTMLInputElement;
  void toggleTradeEngine(target.checked);
}

function closeDetail() {
  detail.value = null;
}
</script>

<template>
  <div class="space-y-6 p-4 sm:p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold">投资组合</h1>
        <p class="text-sm text-muted-foreground">数据库是唯一真实持仓来源，Trade Engine 每 30 分钟给出中线建议。</p>
      </div>
      <div class="flex gap-2">
        <Button
          :variant="market === 'CN' ? 'default' : 'outline'"
          data-testid="market-cn"
          @click="market = 'CN'; load()"
        >
          CN
        </Button>
        <Button
          :variant="market === 'US' ? 'default' : 'outline'"
          data-testid="market-us"
          @click="market = 'US'; load()"
        >
          US
        </Button>
      </div>
    </div>

    <ApiErrorAlert
      v-if="error"
      :error="error"
    />

    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Card><CardHeader><CardDescription>总资产</CardDescription><CardTitle data-testid="total-asset">{{ fmt(totalAsset) }}</CardTitle></CardHeader></Card>
      <Card><CardHeader><CardDescription>现金</CardDescription><CardTitle data-testid="cash">{{ fmt(cash) }}</CardTitle></CardHeader></Card>
      <Card><CardHeader><CardDescription>持仓市值</CardDescription><CardTitle>{{ fmt(marketValue) }}</CardTitle></CardHeader></Card>
      <Card><CardHeader><CardDescription>总仓位</CardDescription><CardTitle>{{ exposure ? `${(Number(exposure) * 100).toFixed(1)}%` : '-' }}</CardTitle></CardHeader></Card>
    </div>

    <div class="flex flex-wrap gap-2">
      <Button data-testid="action-deposit" @click="openForm('deposit')">入金</Button>
      <Button variant="outline" data-testid="action-withdraw" @click="openForm('withdraw')">出金</Button>
      <Button variant="outline" data-testid="action-buy" @click="openForm('buy')">买入</Button>
    </div>

    <Card>
      <CardHeader>
        <CardTitle>持仓</CardTitle>
        <CardDescription>{{ account?.name || '默认账户' }}</CardDescription>
      </CardHeader>
      <CardContent>
        <Empty v-if="!loading && !positions.length">
          <EmptyHeader>
            <EmptyTitle>暂无持仓</EmptyTitle>
            <EmptyDescription>先入金，再记录买入。</EmptyDescription>
          </EmptyHeader>
        </Empty>
        <Table v-else>
          <TableHeader>
            <TableRow>
              <TableHead>股票</TableHead>
              <TableHead>现价</TableHead>
              <TableHead>数量（股）</TableHead>
              <TableHead>平均成本</TableHead>
              <TableHead>市值</TableHead>
              <TableHead>仓位</TableHead>
              <TableHead>盈亏</TableHead>
              <TableHead>Trade Engine</TableHead>
              <TableHead>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="row in positions"
              :key="row.id"
              data-testid="position-row"
            >
              <TableCell>
                <button class="text-left font-medium" @click="openDetail(row)">{{ row.symbol }}</button>
              </TableCell>
              <TableCell>{{ fmt(row.currentPrice) }}</TableCell>
              <TableCell>{{ fmt(row.quantity) }}</TableCell>
              <TableCell>{{ fmt(row.averageCost) }}</TableCell>
              <TableCell>{{ fmt(row.marketValue) }}</TableCell>
              <TableCell>{{ row.weight ? `${(Number(row.weight) * 100).toFixed(1)}%` : '-' }}</TableCell>
              <TableCell>{{ fmt(row.unrealizedPnl) }}</TableCell>
              <TableCell>{{ engineBySymbol[row.symbol]?.action || '-' }}</TableCell>
              <TableCell class="space-x-2">
                <Button size="sm" variant="outline" @click="openForm('buy', row)">买入</Button>
                <Button size="sm" variant="outline" @click="openForm('sell', row)">卖出</Button>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>

    <Dialog :open="formOpen" @update:open="formOpen = $event">
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>{{ { buy: '买入', sell: '卖出', deposit: '入金', withdraw: '出金' }[formKind] }}</DialogTitle>
          <DialogDescription>立即写入数据库真实持仓。</DialogDescription>
        </DialogHeader>
        <div class="space-y-3">
          <template v-if="formKind === 'buy' || formKind === 'sell'">
            <div v-if="formKind === 'buy'">
              <Label>股票</Label>
              <Input v-model="formSymbol" data-testid="form-symbol" placeholder="600519.SH" />
            </div>
            <div>
              <Label>数量（股）</Label>
              <Input v-model="formQuantity" data-testid="form-quantity" />
            </div>
            <div>
              <Label>价格</Label>
              <Input v-model="formPrice" data-testid="form-price" />
            </div>
          </template>
          <div v-else>
            <Label>金额</Label>
            <Input v-model="formAmount" data-testid="form-amount" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" @click="formOpen = false">取消</Button>
          <Button data-testid="form-submit" :disabled="saving" @click="submitForm">确认</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog :open="!!detail" @update:open="value => { if (!value) closeDetail(); }">
      <DialogContent class="max-h-[calc(100dvh-2rem)] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{{ detail?.symbol }}</DialogTitle>
          <DialogDescription>当前持仓、Trade Engine 状态与操作记录</DialogDescription>
        </DialogHeader>
        <div v-if="detail" class="space-y-4">
          <p>数量 {{ fmt(detail.quantity) }} · 成本 {{ fmt(detail.averageCost) }} · 市值 {{ fmt(detail.marketValue) }}</p>
          <label class="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              class="mt-1"
              data-testid="trade-engine-enabled"
              :checked="detail.tradeEngineEnabled !== false"
              @change="onTradeEngineChange($event)"
            />
            <span>
              <span class="font-medium">交易提醒</span>
              <span class="mt-1 block text-xs text-muted-foreground">关闭后，该持仓不运行 Strategy，系统也不会主动给出调仓指令，但仍计入账户 NAV 与组合风险。</span>
            </span>
          </label>
          <p>适用策略 {{ (engineView?.strategies || ['exit_v1', 'add_v1']).join(' / ') }} · 允许 Trade Engine {{ detail.tradeEngineEnabled === false ? '关闭' : '开启' }}</p>
          <p>最新正式信号 {{ engineView?.action || '-' }} · 保护价 {{ engineView?.activeStop || '-' }} · 阶段 {{ engineView?.profitStage || '-' }}</p>
          <p v-if="engineView?.llmReason">LLM最终判断 {{ engineView.llmReason }}</p>
          <DailyKLineCard :symbol="detail.symbol" :markers="markers" marker-caption="操作 BST" />
          <div>
            <h3 class="mb-2 text-sm font-semibold">操作记录</h3>
            <p v-for="item in operations" :key="item.executedAt + item.side">
              {{ item.executedAt }} {{ item.side }} {{ item.quantity }} @{{ item.price }}
            </p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>
