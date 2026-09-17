<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import {
  holdingsApi,
  type HoldingsAccount,
  type HoldingsPosition,
  type HoldingsSource,
  type RiskEventView,
  type RiskPositionView,
} from '@/api/holdings';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import LoadingButton from '@/components/app/LoadingButton.vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute } from 'vue-router';

const route = useRoute();
const loading = ref(false);
const connecting = ref(false);
const syncing = ref(false);
const error = ref<ParsedApiError | null>(null);
const spreadsheetId = ref('');
const source = ref<HoldingsSource | null>(null);
const accounts = ref<HoldingsAccount[]>([]);
const positions = ref<HoldingsPosition[]>([]);
const riskPositions = ref<RiskPositionView[]>([]);
const events = ref<RiskEventView[]>([]);
const vwapMode = ref('exact_or_proxy');
const loadGeneration = ref(0);
const policySnapshot = ref<Record<string, unknown>>({});
let pollTimer: number | null = null;
const googleStatus = computed(() => String(route.query.google || ''));

const sourceLabel = computed(() => {
  if (!source.value) return '未连接';
  return `${source.value.authStatus} / ${source.value.syncStatus || 'IDLE'}`;
});

async function load() {
  const generation = ++loadGeneration.value;
  loading.value = true;
  error.value = null;
  try {
    source.value = await holdingsApi.source();
    const [snap, risk, policy] = await Promise.all([
      holdingsApi.snapshot(),
      holdingsApi.risk(),
      holdingsApi.policy(),
    ]);
    if (generation !== loadGeneration.value) return;
    accounts.value = snap.snapshot?.accounts || [];
    positions.value = snap.snapshot?.positions || [];
    riskPositions.value = risk.positions;
    events.value = risk.events;
    policySnapshot.value = { ...(policy.policy || {}) };
    vwapMode.value = policy.policy.vwapMode || 'exact_or_proxy';
  } catch (err) {
    if (generation !== loadGeneration.value) return;
    error.value = getParsedApiError(err);
  } finally {
    if (generation === loadGeneration.value) loading.value = false;
  }
}

function stopPoll() {
  if (pollTimer != null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

function startPoll() {
  stopPoll();
  pollTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible') {
      void load();
    }
  }, 15000);
}

function onVisibility() {
  if (document.visibilityState === 'visible') {
    void load();
    startPoll();
  } else {
    stopPoll();
  }
}

async function connect() {
  connecting.value = true;
  error.value = null;
  try {
    const result = await holdingsApi.connect(spreadsheetId.value.trim());
    window.location.assign(result.authorization_url);
  } catch (err) {
    error.value = getParsedApiError(err);
    connecting.value = false;
  }
}

async function disconnect() {
  error.value = null;
  await holdingsApi.disconnect();
  await load();
}

async function sync() {
  syncing.value = true;
  error.value = null;
  try {
    const started = source.value?.publishedGeneration ?? 0;
    const result = await holdingsApi.sync();
    if (result.status === 'queued') {
      for (let attempt = 0; attempt < 20; attempt += 1) {
        await load();
        const generation = source.value?.publishedGeneration ?? 0;
        const status = source.value?.syncStatus;
        if (generation > started || status === 'OK' || status === 'REJECTED' || status === 'UNAVAILABLE') {
          break;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
      }
    } else {
      await load();
    }
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    syncing.value = false;
  }
}

async function savePolicy() {
  error.value = null;
  await holdingsApi.updatePolicy({ ...policySnapshot.value, vwap_mode: vwapMode.value });
  await load();
}

async function cancelPlan(row: RiskPositionView) {
  error.value = null;
  await holdingsApi.cancelPlan({
    accountId: row.accountId,
    positionId: row.positionId,
    expectedStateVersion: row.rowVersion,
    reason: 'manual_cancel',
  });
  await load();
}

function vwapLabel(evidence: Record<string, unknown> | undefined) {
  const mode = String(evidence?.vwap_mode || evidence?.vwapMode || 'UNAVAILABLE');
  return mode;
}

function planTarget(row: RiskPositionView) {
  const plan = row.activePlan || {};
  return String(plan.position_target || plan.positionTarget || '');
}

function currentQuantity(row: RiskPositionView) {
  const plan = row.activePlan || {};
  return String(row.currentQuantity || plan.current_quantity || plan.currentQuantity || '');
}

function reduceQuantity(row: RiskPositionView) {
  const plan = row.activePlan || {};
  return String(row.reduceQuantity || plan.reduce_quantity || plan.reduceQuantity || '');
}

function protectionPrices(row: RiskPositionView) {
  const legs = (row.legsState as { legs?: Record<string, { active_stop?: string; activeStop?: string }> } | null)?.legs || {};
  return Object.values(legs)
    .map((leg) => String(leg.active_stop || leg.activeStop || ''))
    .filter(Boolean)
    .join(' / ');
}

function legStage(positionId: string, legId: string) {
  const state = riskPositions.value.find((row) => row.positionId === positionId)?.legsState as
    | { legs?: Record<string, { profit_stage?: string; profitStage?: string }> }
    | null
    | undefined;
  return state?.legs?.[legId]?.profit_stage || state?.legs?.[legId]?.profitStage || '-';
}

onMounted(() => {
  void load();
  startPoll();
  document.addEventListener('visibilitychange', onVisibility);
});
onUnmounted(() => {
  stopPoll();
  document.removeEventListener('visibilitychange', onVisibility);
});
</script>

<template>
  <div class="space-y-6" data-testid="holdings-page">
    <Card>
      <CardHeader>
        <CardTitle>Google Sheet 持仓</CardTitle>
        <CardDescription>
          Sheet 是唯一持仓编辑源。本页只读同步，不在系统内改仓或自动下单。风险摘要会发送到现有全局 Telegram/ntfy 渠道；未配置渠道也不阻塞风控。
        </CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <ApiErrorAlert v-if="error" :error="error" />
        <p v-if="googleStatus" class="text-sm text-muted-foreground">Google 授权结果：{{ googleStatus }}</p>
        <div class="flex flex-wrap items-end gap-3">
          <label class="min-w-64 flex-1 space-y-1 text-sm">
            <span>Spreadsheet ID 或 docs.google.com 链接</span>
            <Input v-model="spreadsheetId" data-testid="spreadsheet-input" placeholder="1abc... 或表格 URL" />
          </label>
          <LoadingButton :loading="connecting" data-testid="connect-button" @click="connect">连接 Google</LoadingButton>
          <LoadingButton :loading="syncing" variant="secondary" data-testid="sync-button" @click="sync">立即同步</LoadingButton>
          <Button variant="outline" data-testid="disconnect-button" @click="disconnect">断开</Button>
        </div>
        <p class="text-sm" data-testid="source-status">状态：{{ sourceLabel }}</p>
        <p class="text-xs text-muted-foreground">
          未覆盖的港股/期权等会保留并标记，不按零处理。Google token、OAuth code 和完整表格不会进入通知。
        </p>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>账户与持仓</CardTitle>
        <CardDescription>CORE/ADDON 独立保护基准；同一证券的多条腿汇总为单票风险。</CardDescription>
      </CardHeader>
      <CardContent>
        <Empty v-if="!loading && !accounts.length">
          <EmptyHeader>
            <EmptyTitle>还没有已发布的持仓快照</EmptyTitle>
            <EmptyDescription>连接 Google Sheet 并完成同步后，这里会显示账户和腿。</EmptyDescription>
          </EmptyHeader>
        </Empty>
        <div v-else class="space-y-6">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>账户</TableHead>
                <TableHead>币种</TableHead>
                <TableHead>净资产</TableHead>
                <TableHead>校验</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="account in accounts" :key="account.accountId">
                <TableCell>{{ account.accountName }} / {{ account.accountId }}</TableCell>
                <TableCell>{{ account.baseCurrency }}</TableCell>
                <TableCell>{{ account.netAsset || '未知' }}</TableCell>
                <TableCell>{{ account.validity }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
          <Table data-testid="positions-table">
            <TableHeader>
              <TableRow>
                <TableHead>仓位</TableHead>
                <TableHead>证券</TableHead>
                <TableHead>腿</TableHead>
                <TableHead>角色</TableHead>
                <TableHead>数量</TableHead>
                <TableHead>成本</TableHead>
                <TableHead>覆盖</TableHead>
                <TableHead>阶段</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="leg in positions.flatMap((item) => item.legs)" :key="`${leg.accountId}-${leg.legId}`">
                <TableCell>{{ leg.positionId }}</TableCell>
                <TableCell>{{ leg.canonicalSymbol || leg.symbol }}</TableCell>
                <TableCell>{{ leg.legId }}</TableCell>
                <TableCell>{{ leg.legRole }}</TableCell>
                <TableCell>{{ leg.quantity }}</TableCell>
                <TableCell>{{ leg.entryPrice }}</TableCell>
                <TableCell>{{ leg.coverage }}</TableCell>
                <TableCell>{{ legStage(leg.positionId, leg.legId) }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>风控状态</CardTitle>
        <CardDescription>
          硬保护看实时报价；5m 软规则使用 CN 新浪 / US yfinance。VWAP 展示 EXACT / PROXY / UNAVAILABLE。
        </CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="flex flex-wrap items-center gap-3">
          <label class="text-sm">
            VWAP 口径
            <select v-model="vwapMode" class="ml-2 rounded border px-2 py-1" data-testid="vwap-mode">
              <option value="exact_or_proxy">exact_or_proxy</option>
              <option value="exact_only">exact_only</option>
            </select>
          </label>
          <Button variant="secondary" size="sm" data-testid="save-policy" @click="savePolicy">保存口径</Button>
        </div>
        <Table data-testid="risk-table">
          <TableHeader>
              <TableRow>
                <TableHead>仓位</TableHead>
                <TableHead>证券</TableHead>
                <TableHead>当前</TableHead>
                <TableHead>目标</TableHead>
                <TableHead>减少</TableHead>
                <TableHead>保护价</TableHead>
                <TableHead>计划</TableHead>
                <TableHead>5m / 报价</TableHead>
                <TableHead>执行</TableHead>
                <TableHead>数据时间</TableHead>
                <TableHead></TableHead>
              </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="row in riskPositions" :key="`${row.accountId}-${row.positionId}`">
              <TableCell>{{ row.positionId }}</TableCell>
              <TableCell>{{ row.symbol }}</TableCell>
              <TableCell>{{ currentQuantity(row) }}</TableCell>
              <TableCell>{{ planTarget(row) }}</TableCell>
              <TableCell>{{ reduceQuantity(row) }}</TableCell>
              <TableCell>{{ protectionPrices(row) || '-' }}</TableCell>
              <TableCell>{{ row.planStatus }} / {{ row.planAction }}</TableCell>
              <TableCell>{{ row.fiveMinuteStatus || '-' }} / {{ row.quoteStatus || '-' }}</TableCell>
              <TableCell>{{ row.execution || (row.activePlan || {}).execution || '-' }}</TableCell>
              <TableCell>{{ row.lastBarEnd || row.lastQuoteAsOf || '未知' }}</TableCell>
              <TableCell>
                <Button
                  v-if="row.planStatus === 'PENDING'"
                  size="sm"
                  variant="outline"
                  :data-testid="`cancel-${row.positionId}`"
                  @click="cancelPlan(row)"
                >
                  取消计划
                </Button>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <Table data-testid="events-table">
          <TableHeader>
            <TableRow>
              <TableHead>时间</TableHead>
              <TableHead>事件</TableHead>
              <TableHead>动作</TableHead>
              <TableHead>目标</TableHead>
              <TableHead>VWAP</TableHead>
              <TableHead>通知</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="item in events" :key="item.id">
              <TableCell>{{ item.createdAt }}</TableCell>
              <TableCell>{{ item.eventType }}</TableCell>
              <TableCell>{{ item.action }}</TableCell>
              <TableCell>{{ item.targetQuantity }}</TableCell>
              <TableCell>{{ vwapLabel(item.evidence) }}</TableCell>
              <TableCell>{{ item.notificationId ? item.pushStatus : '未创建' }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  </div>
</template>
