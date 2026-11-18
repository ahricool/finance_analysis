<script setup lang="ts">
import { computed, ref } from 'vue';
import { Activity, ArrowDownLeft, ArrowUpRight, Clock3, ShieldCheck } from 'lucide-vue-next';
import type { IntradayOptionsSnapshot, SimTrade, SimulationPlan, SimulationSnapshot } from '@/api/intradayOptions';
import { useCurrentTime } from '@/composables/useCurrentTime';
import { sortField, sortTime } from '@/composables/useTableSort';
import { clock, fmt, pct, tone, opportunityKinds, opportunityStates, confirmationLabel } from './labels';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import SimulationTable from './SimulationTable.vue';

type SimEvent = SimulationSnapshot['events'][number];
const props = defineProps<{ snapshot: IntradayOptionsSnapshot; disconnected: boolean }>();
const now = useCurrentTime(1000);
const selected = ref('all');
const matches = (symbol: string) => selected.value === 'all' || selected.value === symbol;
const quoteFor = (symbol: string) => props.snapshot.items.find(r => r.symbol === symbol)?.simulation
  ?? props.snapshot.simulation?.states.find(s => s.symbol === symbol);
const state = computed(() => quoteFor(selected.value));
const staleState = (symbol: string) => {
  const at = quoteFor(symbol)?.calculatedAt;
  const age = at ? now.value.getTime() - Date.parse(at) : NaN;
  return props.disconnected || !Number.isFinite(age) || age < 0 || age > 15000;
};
const stale = computed(() => staleState(selected.value));
const positions = computed(() => (props.snapshot.simulation?.states ?? []).flatMap(s => s.position && matches(s.symbol) ? [s.position] : []));
const cutoff = computed(() => state.value?.cutoff ?? props.snapshot.simulation?.states.find(s => s.cutoff)?.cutoff
  ?? props.snapshot.items.find(r => r.simulation?.cutoff)?.simulation?.cutoff);
const remaining = computed(() => cutoff.value && Number.isFinite(Date.parse(cutoff.value)) ? Math.max(0, Math.ceil((Date.parse(cutoff.value) - now.value.getTime()) / 60000)) : null);
const phase = computed(() => props.snapshot.marketStatus === 'preopen' ? 'preopen'
  : props.snapshot.marketStatus === 'closed' ? 'closed' : remaining.value == null ? 'unknown' : remaining.value === 0 ? 'stopped' : 'active');
const phaseLabel = computed(() => ({ preopen: '等待开盘', closed: '非交易时间', stopped: '今日已停止进场', active: '交易窗口内', unknown: '交易日历待同步' })[phase.value]);
const entryPaused = computed(() => phase.value !== 'active');
const events = computed(() => [...new Map((props.snapshot.simulation?.events ?? []).filter(e => matches(e.symbol)).map(e => [e.id, e])).values()].sort((a, b) =>
  (sortTime(b.at) ?? -Infinity) - (sortTime(a.at) ?? -Infinity) || b.id - a.id));
const importantEvents = computed(() => events.value.filter(e => ['entry', 'exit', 'hold'].includes(e.kind)).slice(0, 30));
const otherEvents = computed(() => events.value.filter(e => !['entry', 'exit', 'hold'].includes(e.kind)));
function eventSide(e: SimEvent) {
  return e.side ?? e.trade?.side
    ?? props.snapshot.simulation?.trades.find(t => t.id === e.tradeId)?.side
    ?? props.snapshot.simulation?.states.find(s => s.position?.id === e.tradeId)?.position?.side;
}
const sideLabel = (side?: number) => side === 1 ? '做多' : side === -1 ? '做空' : '—';
const eventLabel = (kind: string) => ({ entry: '模拟进场', exit: '模拟退场', hold: '持有变化', data: '行情状态', confirmed: '形态确认' })[kind] ?? kind;
const trades = computed(() => props.snapshot.simulation?.trades.filter(t => matches(t.symbol)) ?? []);
const normalTrades = computed(() => trades.value.filter(t => !t.estimated));
const averageReturn = computed(() => normalTrades.value.length ? normalTrades.value.reduce((sum, t) => sum + t.returnPct, 0) / normalTrades.value.length : null);
const duration = (at: string) => Math.max(0, Math.floor((now.value.getTime() - Date.parse(at)) / 60000));
const tradeMinutes = (t: SimTrade) => t.exitAt ? Math.max(0, (Date.parse(t.exitAt) - Date.parse(t.entryAt)) / 60000) : duration(t.entryAt);
const price = (value: number | null | undefined) => fmt(value, 2);
const planReason = (p: SimulationPlan) => entryPaused.value ? `${phaseLabel.value}，不产生新信号` : stale.value ? '连接或计算延迟，当前入场资格未知' : p.executionReason;
const statLabel = (label: string) => {
  const [kind, side] = label.split('/');
  return side ? `${opportunityKinds[kind as SimulationPlan['kind']] ?? kind} · ${sideLabel(Number(side))}` : label;
};
const positionColumns = [
  { key: 'symbol', label: '模拟持仓' }, { key: 'entryAt', label: '进场时间' }, { key: 'entryPrice', label: '入场价', numeric: true },
  { key: 'currentPrice', label: '当前有效价', numeric: true }, { key: 'returnPct', label: '持有中收益', numeric: true },
  { key: 'duration', label: '持有时长', numeric: true }, { key: 'protection', label: '保护 / 失效位', numeric: true },
  { key: 'target', label: '目标位', numeric: true },
];
const eventColumns = [
  { key: 'at', label: '发生时间' }, { key: 'symbol', label: '标的 / 方向' },
  { key: 'kind', label: '模拟动作' }, { key: 'price', label: '标的价格', numeric: true }, { key: 'reason', label: '原因与下一步' },
];
const planColumns = [
  { key: 'kind', label: '机会 / 方向' }, { key: 'confirmedAt', label: '首次确认时间' }, { key: 'status', label: '形态 / 当前资格' },
  { key: 'entryLow', label: '入场区间', numeric: true }, { key: 'invalidation', label: '结构失效位', numeric: true },
  { key: 'target', label: '目标位', numeric: true }, { key: 'remainingSpace', label: '剩余空间 / 收益风险比', numeric: true },
];
const historyColumns = [
  { key: 'symbol', label: '标的 / 方向' }, { key: 'kind', label: '形态' }, { key: 'entryAt', label: '进场时间' },
  { key: 'exitAt', label: '退场时间' }, { key: 'entryPrice', label: '进场价', numeric: true },
  { key: 'exitPrice', label: '退场价', numeric: true }, { key: 'returnPct', label: '已实现收益', numeric: true },
  { key: 'exitReason', label: '退出原因' },
];
const statColumns = [
  { key: 'label', label: '分组' }, { key: 'count', label: '笔数', numeric: true }, { key: 'winRate', label: '胜率', numeric: true },
  { key: 'averageReturn', label: '每笔平均', numeric: true }, { key: 'averageWin', label: '平均盈利', numeric: true },
  { key: 'averageLoss', label: '平均亏损', numeric: true }, { key: 'averageDuration', label: '平均持有', numeric: true },
];
function positionValue(t: SimTrade, key: string) {
  if (key === 'entryAt') return sortTime(t.entryAt);
  return key === 'currentPrice' ? quoteFor(t.symbol)?.currentPrice : key === 'duration' ? tradeMinutes(t) : sortField(t, key);
}
function eventValue(e: SimEvent, key: string) {
  if (key === 'at') return sortTime(e.at);
  if (key === 'kind') return ['entry', 'hold', 'exit', 'confirmed', 'data'].indexOf(e.kind);
  if (key === 'price') return e.kind === 'exit' ? e.trade?.exitPrice : e.kind === 'entry' ? e.trade?.entryPrice : null;
  return sortField(e, key);
}
function planValue(p: SimulationPlan, key: string) {
  if (key === 'confirmedAt') return sortTime(p.confirmedAt);
  return key === 'status' ? ['confirmed', 'forming', 'extended', 'expired', 'invalidated'].indexOf(p.status) : sortField(p, key);
}
function historyValue(t: SimTrade, key: string) {
  return key === 'entryAt' || key === 'exitAt' ? sortTime(t[key]) : sortField(t, key);
}
</script>

<template>
  <section
    class="min-w-0 overflow-hidden rounded-xl border bg-card shadow-sm"
    aria-label="日内信号与虚拟交易"
  >
    <header class="flex flex-wrap items-start justify-between gap-4 border-b bg-muted/20 px-5 py-5">
      <div class="flex items-start gap-3">
        <div class="rounded-lg border bg-background p-2.5">
          <Activity class="size-5 text-muted-foreground" />
        </div>
        <div>
          <h2 class="text-base font-semibold tracking-tight">
            日内信号与虚拟交易 <span class="ml-2 text-xs font-normal text-muted-foreground">模拟</span>
          </h2>
          <p class="mt-1 text-xs text-muted-foreground">
            Underlying simulation · 全观察池独立运行
          </p>
        </div>
      </div>
      <FieldSelect
        v-model="selected"
        class="w-44"
        :options="[{ value: 'all', label: '全部标的' }, ...snapshot.items.map(r => ({ value: r.symbol, label: r.symbol }))]"
        aria-label="模拟标的筛选"
      />
    </header>

    <div class="grid grid-cols-2 divide-x divide-border border-b lg:grid-cols-4">
      <div class="px-5 py-4">
        <p class="text-xs text-muted-foreground">
          当前模拟持仓
        </p>
        <p class="mt-2 text-2xl font-semibold tabular-nums">
          {{ positions.length }} <span class="text-xs font-normal text-muted-foreground">个标的</span>
        </p>
        <p class="mt-1 text-xs text-muted-foreground">
          每个标的最多一笔
        </p>
      </div>
      <div class="px-5 py-4">
        <p class="text-xs text-muted-foreground">
          当日已完成
        </p>
        <p class="mt-2 text-2xl font-semibold tabular-nums">
          {{ normalTrades.length }} <span class="text-xs font-normal text-muted-foreground">笔正常模拟</span>
        </p>
        <p class="mt-1 text-xs text-muted-foreground">
          另有 {{ trades.length - normalTrades.length }} 笔估算退出
        </p>
      </div>
      <div class="border-t px-5 py-4 lg:border-t-0">
        <p class="text-xs text-muted-foreground">
          已完成 · 每笔平均收益
        </p>
        <p
          class="mt-2 text-2xl font-semibold tabular-nums"
          :class="tone(averageReturn)"
        >
          {{ pct(averageReturn) }}
        </p>
        <p class="mt-1 text-xs text-muted-foreground">
          仅正常模拟 · 非组合收益
        </p>
      </div>
      <div class="border-t px-5 py-4 lg:border-t-0">
        <p class="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock3 class="size-3.5" />{{ phaseLabel }}
        </p>
        <p class="mt-2 text-xl font-semibold tabular-nums">
          {{ remaining != null && phase === 'active' ? `${remaining} 分钟` : phase === 'preopen' ? '尚未开盘' : phase === 'stopped' ? '已截止' : phase === 'unknown' ? '待同步' : '休市' }}
        </p>
        <p class="mt-1 text-xs text-muted-foreground">
          {{ cutoff ? `停止交易 ${clock(cutoff)} · 纽约` : phase === 'unknown' ? '日历缺失 · 暂停信号' : '当日无交易窗口' }}
        </p>
      </div>
    </div>

    <div class="flex flex-wrap items-center justify-between gap-2 border-b px-5 py-2.5 text-xs text-muted-foreground">
      <span class="flex items-center gap-2"><span
        class="size-1.5 rounded-full"
        :class="disconnected ? 'bg-destructive' : 'bg-foreground/60'"
      />{{ disconnected ? '连接中断，仅显示历史状态' : entryPaused ? '信号暂停 · 非交易窗口不产生新信号或行情告警' : '后台持续监测 · 每 5 秒更新' }}</span>
      <span>快照 {{ clock(snapshot.generatedAt) }} · 时间均为纽约</span>
    </div>

    <section aria-label="当前模拟持仓">
      <div class="flex items-center justify-between px-5 pb-3 pt-5">
        <h3 class="flex items-center gap-2 text-sm font-semibold">
          <ShieldCheck class="size-4 text-muted-foreground" />当前模拟持仓
        </h3>
        <span class="text-xs text-muted-foreground">持有中不加仓、不反手</span>
      </div>
      <SimulationTable
        :rows="positions"
        :columns="positionColumns"
        default-time-key="entryAt"
        :value="positionValue"
        :row-key="t => t.id"
        row-testid="simulation-position"
        label="当前模拟持仓表"
        :empty="entryPaused ? `${phaseLabel} · 模拟空仓` : '模拟空仓 · 等待独立合格机会'"
      >
        <template #cell="{ row: p, column }">
          <template v-if="column === 'symbol'">
            <p class="font-semibold">
              {{ p.symbol }}
            </p>
            <p
              class="mt-1 text-xs"
              :class="tone(p.side)"
            >
              模拟持有{{ p.side === 1 ? '多' : '空' }} <span class="text-muted-foreground">· {{ opportunityKinds[p.kind] }}</span>
            </p>
          </template>
          <template v-else-if="column === 'entryAt'">
            {{ clock(p.entryAt) }}
          </template>
          <template v-else-if="column === 'entryPrice'">
            {{ price(p.entryPrice) }}
          </template>
          <template v-else-if="column === 'currentPrice'">
            {{ price(quoteFor(p.symbol)?.currentPrice) }}<p class="mt-1 text-xs text-muted-foreground">
              行情 {{ clock(quoteFor(p.symbol)?.quoteTime) }}
            </p>
          </template>
          <template v-else-if="column === 'returnPct'">
            <span
              class="font-semibold"
              :class="tone(p.returnPct)"
            >{{ pct(p.returnPct) }}</span>
            <p class="mt-1 text-xs text-muted-foreground">
              估值 {{ clock(p.lastPriceAt) }}
            </p>
          </template>
          <template v-else-if="column === 'duration'">
            {{ duration(p.entryAt) }} 分钟<p class="mt-1 text-xs text-muted-foreground">
              {{ staleState(p.symbol) ? '计算延迟 · 保留旧估值' : `计算 ${clock(quoteFor(p.symbol)?.calculatedAt)}` }}
            </p>
          </template>
          <template v-else-if="column === 'protection'">
            {{ price(p.protection) }}<p class="mt-1 text-xs text-muted-foreground">
              原始 {{ price(p.invalidation) }}
            </p>
          </template>
          <template v-else-if="column === 'target'">
            {{ price(p.target) }}<p class="mt-1 text-xs text-muted-foreground">
              {{ p.target == null ? '结构目标未知' : '触及后模拟退场' }}
            </p>
          </template>
        </template>
      </SimulationTable>
      <p class="border-b px-5 py-3 text-xs leading-relaxed text-muted-foreground">
        下一步：监测保护位、目标位、未推进超时及截止清仓。估值使用最后有效价格；行情或连接异常时保留价格时间。
      </p>
    </section>

    <section
      aria-label="最近模拟进退场消息"
      class="border-b"
    >
      <div class="flex items-center justify-between px-5 pb-3 pt-5">
        <h3 class="text-sm font-semibold">
          最近模拟进退场与持有变化
        </h3>
        <span class="text-xs text-muted-foreground">最近 30 条 · 默认最新优先</span>
      </div>
      <div class="max-h-96 overflow-y-auto">
        <SimulationTable
          :rows="importantEvents"
          :columns="eventColumns"
          default-time-key="at"
          :value="eventValue"
          :row-key="e => e.id"
          row-testid="simulation-event"
          label="模拟交易动态表"
          empty="暂无进退场或重要持有变化"
        >
          <template #cell="{ row: e, column }">
            <template v-if="column === 'at'">
              <span class="tabular-nums">{{ clock(e.at) }}</span>
            </template>
            <template v-else-if="column === 'symbol'">
              <span class="font-medium">{{ e.symbol }}</span><span
                class="ml-2 text-xs"
                :class="tone(eventSide(e))"
              >{{ sideLabel(eventSide(e)) }}</span>
            </template>
            <template v-else-if="column === 'kind'">
              <span class="inline-flex items-center gap-1.5 text-xs"><ArrowUpRight
                v-if="e.kind === 'entry'"
                class="size-3.5"
              /><ArrowDownLeft
                v-else-if="e.kind === 'exit'"
                class="size-3.5"
              /><ShieldCheck
                v-else
                class="size-3.5"
              />{{ eventLabel(e.kind) }}</span>
            </template>
            <template v-else-if="column === 'price'">
              {{ price(eventValue(e, 'price') as number | null) }}
            </template>
            <template v-else-if="column === 'reason'">
              <p class="min-w-48 max-w-md whitespace-normal leading-relaxed">
                {{ e.reason }}
              </p>
              <p
                v-if="e.trade"
                class="mt-1 text-xs text-muted-foreground"
              >
                {{ opportunityKinds[e.trade.kind] }}<template v-if="e.trade.confirmationMethod">
                  · {{ confirmationLabel(e.trade.confirmationMethod) }}
                </template>
              </p>
              <p
                v-if="e.trade?.estimated"
                class="mt-1 max-w-md whitespace-normal text-xs text-muted-foreground"
              >
                估算退出 · 价格 {{ clock(e.trade.exitPriceAt) }} / 计划 {{ clock(e.trade.plannedExitAt) }} / 处理 {{ clock(e.trade.exitAt) }}；{{ e.trade.anomaly }}
              </p>
            </template>
          </template>
        </SimulationTable>
      </div>
    </section>

    <section
      v-if="selected !== 'all'"
      class="border-b"
      aria-label="单标的机会计划"
    >
      <div class="px-5 pb-3 pt-5">
        <h3 class="text-sm font-semibold">
          {{ selected }} · 机会与交易计划
        </h3><p class="mt-1 text-xs text-muted-foreground">
          行情 {{ clock(state?.quoteTime) }} · 计算 {{ clock(state?.calculatedAt) }}
        </p>
      </div>
      <SimulationTable
        :rows="state?.plans ?? []"
        :columns="planColumns"
        default-time-key="confirmedAt"
        :value="planValue"
        :row-key="p => p.structureId"
        label="机会计划表"
        empty="尚无可观察机会"
      >
        <template #cell="{ row: p, column }">
          <template v-if="column === 'kind'">
            <p class="font-medium">
              {{ opportunityKinds[p.kind] }}
            </p><p
              class="mt-1 text-xs"
              :class="tone(p.direction === 'bullish' ? 1 : -1)"
            >
              {{ p.direction === 'bullish' ? '做多' : '做空' }}
            </p>
          </template>
          <template v-else-if="column === 'confirmedAt'">
            {{ clock(p.confirmedAt) }}<p class="mt-1 text-xs text-muted-foreground">
              {{ p.ageSeconds == null ? '待确认' : `${Math.floor(p.ageSeconds / 60)}分钟` }}
            </p>
          </template>
          <template v-else-if="column === 'status'">
            <p>{{ opportunityStates[p.status] }} · {{ confirmationLabel(p.confirmationMethod) }}</p><p class="mt-1 max-w-64 whitespace-normal text-xs text-muted-foreground">
              {{ entryPaused ? phaseLabel : stale ? '连接或计算延迟，当前机会资格未知' : p.opportunityReason }}
            </p><p class="mt-1 max-w-64 whitespace-normal text-xs">
              {{ planReason(p) }}
            </p>
          </template>
          <template v-else-if="column === 'entryLow'">
            {{ price(p.entryLow) }}–{{ price(p.entryHigh) }}
          </template>
          <template v-else-if="column === 'invalidation'">
            {{ price(p.invalidation) }}
          </template>
          <template v-else-if="column === 'target'">
            {{ price(p.target) }}<p class="mt-1 text-xs text-muted-foreground">
              {{ p.targetSource }}
            </p>
          </template>
          <template v-else-if="column === 'remainingSpace'">
            {{ price(p.remainingSpace) }}<p class="mt-1 text-xs text-muted-foreground">
              收益风险比 {{ fmt(p.rewardRisk, 2) }}
            </p>
          </template>
        </template>
      </SimulationTable>
      <div class="grid divide-y border-t sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <div
          v-for="r in state?.relativeStrength ?? []"
          :key="r.minutes"
          class="px-5 py-3"
        >
          <p class="text-xs text-muted-foreground">
            相对 QQQ · {{ r.minutes }}分钟
          </p><p
            class="mt-1 text-sm font-medium"
            :class="tone(r.value)"
          >
            {{ r.value == null ? '—' : `${r.value.toFixed(2)} 个百分点` }}
          </p>
          <p class="mt-1 text-xs text-muted-foreground">
            {{ r.value == null ? r.reason : `${clock(r.start)}–${clock(r.end)}` }}
          </p>
        </div>
      </div>
    </section>
    <p
      v-else
      class="border-b px-5 py-3 text-xs text-muted-foreground"
    >
      选择单标的可查看机会计划及相对强弱详情；相对强弱仅供参考，不直接产生买卖信号。
    </p>

    <details class="border-b">
      <summary class="cursor-pointer px-5 py-4 text-sm font-medium">
        当日已完成模拟交易 <span class="ml-2 text-xs font-normal text-muted-foreground">{{ trades.length }} 笔 · 当前筛选</span>
      </summary>
      <SimulationTable
        :rows="trades"
        :columns="historyColumns"
        default-time-key="exitAt"
        :value="historyValue"
        :row-key="t => t.id"
        label="已完成模拟交易表"
        empty="当日尚无已完成模拟交易"
      >
        <template #cell="{ row: t, column }">
          <template v-if="column === 'symbol'">
            <p class="font-medium">
              {{ t.symbol }}
            </p><p
              class="mt-1 text-xs"
              :class="tone(t.side)"
            >
              {{ sideLabel(t.side) }}
            </p>
          </template>
          <template v-else-if="column === 'kind'">
            {{ opportunityKinds[t.kind] }}
            <p
              v-if="t.confirmationMethod"
              class="mt-1 text-xs text-muted-foreground"
            >
              {{ confirmationLabel(t.confirmationMethod) }}
            </p>
          </template>
          <template v-else-if="column === 'entryAt' || column === 'exitAt'">
            {{ clock(t[column]) }}
          </template>
          <template v-else-if="column === 'entryPrice' || column === 'exitPrice'">
            {{ price(t[column]) }}
          </template>
          <template v-else-if="column === 'returnPct'">
            <span :class="tone(t.returnPct)">{{ pct(t.returnPct) }}</span>
          </template>
          <template v-else-if="column === 'exitReason'">
            <p>{{ t.exitReason }}</p><p
              v-if="t.estimated"
              class="mt-1 text-xs text-muted-foreground"
            >
              估算退出 · 单独统计
            </p>
          </template>
        </template>
      </SimulationTable>
    </details>
    <details class="border-b">
      <summary class="cursor-pointer px-5 py-4 text-sm font-medium">
        当日逐笔统计 <span class="ml-2 text-xs font-normal text-muted-foreground">全观察池 · 不代表组合收益</span>
      </summary>
      <SimulationTable
        :rows="snapshot.simulation?.statistics ?? []"
        :columns="statColumns"
        :value="sortField"
        :row-key="s => s.label"
        label="模拟收益统计表"
        empty="暂无可统计的已完成交易"
      >
        <template #cell="{ row: s, column }">
          <template v-if="column === 'label'">
            {{ statLabel(s.label) }}
          </template>
          <template v-else-if="column === 'count'">
            {{ s.count }}
          </template>
          <template v-else-if="column === 'averageDuration'">
            {{ s.averageDuration == null ? '—' : `${Math.round(s.averageDuration / 60)}分钟` }}
          </template>
          <template v-else-if="column === 'winRate'">
            {{ s.winRate == null ? '—' : `${fmt(s.winRate, 1)}%` }}
          </template>
          <template v-else>
            <span :class="tone(sortField(s, column) as number | null)">{{ pct(sortField(s, column) as number | null) }}</span>
          </template>
        </template>
      </SimulationTable>
    </details>
    <details class="border-b">
      <summary class="cursor-pointer px-5 py-4 text-sm font-medium">
        行情与形态记录 <span class="ml-2 text-xs font-normal text-muted-foreground">{{ otherEvents.length }} 条 · 与交易动态分开</span>
      </summary>
      <div class="max-h-72 overflow-y-auto">
        <SimulationTable
          :rows="otherEvents"
          :columns="eventColumns.filter(c => c.key !== 'price')"
          default-time-key="at"
          :value="eventValue"
          :row-key="e => e.id"
          label="行情与形态记录表"
          empty="暂无行情与形态记录"
        >
          <template #cell="{ row: e, column }">
            <template v-if="column === 'at'">
              {{ clock(e.at) }}
            </template>
            <template v-else-if="column === 'symbol'">
              {{ e.symbol }}
            </template>
            <template v-else-if="column === 'kind'">
              {{ eventLabel(e.kind) }}
            </template>
            <template v-else-if="column === 'reason'">
              <p class="max-w-lg whitespace-normal">
                {{ e.reason }}
              </p>
            </template>
          </template>
        </SimulationTable>
      </div>
    </details>
    <details
      v-if="snapshot.simulation?.references"
      class="border-b"
    >
      <summary class="cursor-pointer px-5 py-4 text-sm font-medium">
        市场背景与事件参考 <span class="ml-2 text-xs font-normal text-muted-foreground">不参与入场门槛</span>
      </summary>
      <div class="grid gap-5 px-5 pb-5 md:grid-cols-2">
        <div class="rounded-lg bg-muted/40 p-4">
          <p class="text-sm font-medium">
            QQQ · {{ snapshot.simulation.references.background.label }}
          </p><p class="mt-2 text-xs leading-relaxed text-muted-foreground">
            {{ snapshot.simulation.references.background.reason }}<br>截至 {{ snapshot.simulation.references.background.asOf ?? '未知' }}
          </p>
        </div>
        <div class="rounded-lg bg-muted/40 p-4">
          <p class="text-sm font-medium">
            宏观事件日历
          </p><p class="mt-2 text-xs text-muted-foreground">
            {{ snapshot.simulation.references.macroStatus }}
          </p><p
            v-for="e in snapshot.simulation.references.macro"
            :key="e.title + e.at"
            class="mt-2 text-xs leading-relaxed"
          >
            {{ clock(e.at) }} · {{ e.title }}<br><span class="text-muted-foreground">{{ e.reason }} · 采集 {{ clock(e.asOf) }}</span>
          </p>
        </div>
      </div>
    </details>
    <footer class="bg-muted/20 px-5 py-3 text-xs leading-relaxed text-muted-foreground">
      仅按标的价格模拟，未计手续费和滑点。分数不是胜率，模拟收益不是期权收益；与真实持仓无关。
    </footer>
  </section>
</template>
