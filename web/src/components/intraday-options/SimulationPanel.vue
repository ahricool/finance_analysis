<script setup lang="ts">
import { computed, ref } from 'vue';
import type { IntradayOptionsSnapshot } from '@/api/intradayOptions';
import { useCurrentTime } from '@/composables/useCurrentTime';
import { clock, fmt, pct, opportunityKinds, opportunityStates } from './labels';
import FieldSelect from '@/components/forms/FieldSelect.vue';
const props = defineProps<{ snapshot: IntradayOptionsSnapshot; disconnected: boolean }>();
const now = useCurrentTime(1000);
const selected = ref('all');
const matches = (symbol: string) => selected.value === 'all' || selected.value === symbol;
const row = computed(() => props.snapshot.items.find(r => r.symbol === selected.value));
const state = computed(() => row.value?.simulation);
const stale = computed(() => props.disconnected || !state.value || now.value.getTime() - Date.parse(state.value.calculatedAt) > 15000);
const positions = computed(() => (props.snapshot.simulation?.states ?? []).flatMap(s => s.position && matches(s.symbol) ? [s.position] : []));
const quoteFor = (symbol: string) => props.snapshot.items.find(r => r.symbol === symbol)?.simulation;
const cutoff = computed(() => state.value?.cutoff ?? props.snapshot.items.find(r => r.simulation?.cutoff)?.simulation?.cutoff);
const remaining = computed(() => cutoff.value ? Math.max(0, Math.ceil((Date.parse(cutoff.value) - now.value.getTime()) / 60000)) : null);
const events = computed(() => [...new Map((props.snapshot.simulation?.events ?? []).filter(e => matches(e.symbol)).map(e => [e.id, e])).values()].sort((a, b) => b.id - a.id));
const importantEvents = computed(() => events.value.filter(e => ['entry', 'exit', 'hold'].includes(e.kind)).slice(0, 30));
const otherEvents = computed(() => events.value.filter(e => !['entry', 'exit', 'hold'].includes(e.kind)));
function eventDirection(e: NonNullable<IntradayOptionsSnapshot['simulation']>['events'][number]) {
  const side = e.side ?? e.trade?.side
    ?? props.snapshot.simulation?.trades.find(t => t.id === e.tradeId)?.side
    ?? props.snapshot.simulation?.states.find(s => s.position?.id === e.tradeId)?.position?.side;
  return side === 1 ? '做多' : side === -1 ? '做空' : '方向未知';
}
const trades = computed(() => props.snapshot.simulation?.trades.filter(t => matches(t.symbol)) ?? []);
const duration = (at: string) => Math.max(0, Math.floor((now.value.getTime() - Date.parse(at)) / 60000));
</script>

<template>
  <section
    class="space-y-3 rounded-lg border p-4"
    aria-label="日内信号与虚拟交易"
  >
    <h2 class="font-semibold">
      日内信号与虚拟交易 · 模拟
    </h2>
    <p class="text-sm text-muted-foreground">
      仅按标的价格模拟，未计手续费和滑点；分数不是胜率，模拟收益不是期权收益。与真实持仓无关。
    </p>
    <FieldSelect
      v-model="selected"
      class="w-48"
      :options="[{ value: 'all', label: '全部标的' }, ...snapshot.items.map(r => ({ value: r.symbol, label: r.symbol }))]"
      aria-label="模拟标的筛选"
    />
    <p class="text-sm">
      停止进场 {{ clock(cutoff) }}（纽约） · {{ remaining === 0 ? '今日已停止进场' : remaining == null ? '交易日历暂无' : `距截止 ${remaining} 分钟` }}
    </p>
    <p
      v-if="selected !== 'all'"
      class="text-xs text-muted-foreground"
    >
      行情 {{ clock(state?.quoteTime) }} · 计算 {{ clock(state?.calculatedAt) }} · {{ disconnected ? '连接中断，仅显示历史状态' : '后台持续计算' }}
    </p>
    <div
      v-for="position in positions"
      :key="position.id"
      data-testid="simulation-position"
      class="rounded border p-3 text-sm"
    >
      <strong>{{ position.symbol }} · 模拟持有{{ position.side === 1 ? '多' : '空' }}</strong> · 入场 {{ fmt(position.entryPrice) }} · 当前有效价 {{ fmt(quoteFor(position.symbol)?.currentPrice) }}
      · 持有中 {{ pct(position.returnPct) }} · {{ duration(position.entryAt) }} 分钟
      <p>原始失效 {{ fmt(position.invalidation) }} · 保护位 {{ fmt(position.protection) }} · 目标 {{ fmt(position.target) }}</p>
      <p>下一步：等待保护位、目标、未推进超时或截止退出；持有中不再进场。</p>
      <p class="text-xs text-muted-foreground">
        估值价格截至 {{ clock(position.lastPriceAt) }} · 计算 {{ clock(quoteFor(position.symbol)?.calculatedAt) }}，失联期间保留旧估值。
      </p>
    </div>
    <p
      v-if="!positions.length"
      class="text-sm"
    >
      模拟空仓 · 等待独立合格机会
    </p>
    <div
      v-for="p in state?.plans ?? []"
      :key="p.structureId"
      class="rounded border p-3 text-sm"
    >
      <strong>{{ opportunityKinds[p.kind] }} · {{ p.direction === 'bullish' ? '做多' : '做空' }}</strong>
      <p>形态：{{ opportunityStates[p.status] }} · {{ stale ? '连接或计算延迟，当前机会资格未知' : p.opportunityReason }}</p>
      <p>新增模拟仓位：{{ stale ? '连接或计算延迟，当前入场资格未知' : p.executionReason }}</p>
      <p>首次确认 {{ clock(p.confirmedAt) }} · 年龄 {{ p.ageSeconds == null ? '—' : `${Math.floor(p.ageSeconds / 60)}分钟` }}</p>
      <p>入场区间 {{ fmt(p.entryLow) }}–{{ fmt(p.entryHigh) }} · 失效 {{ fmt(p.invalidation) }} · 目标 {{ fmt(p.target) }}（{{ p.targetSource }}）</p>
      <p>剩余空间 {{ fmt(p.remainingSpace) }} · 标的收益风险比 {{ fmt(p.rewardRisk) }}</p>
    </div>
    <p
      v-if="selected !== 'all' && !state?.plans.length"
      class="text-sm text-muted-foreground"
    >
      尚无可观察机会
    </p>
    <div class="flex flex-wrap gap-3 text-xs">
      <span
        v-for="r in state?.relativeStrength ?? []"
        :key="r.minutes"
      >相对QQQ {{ r.minutes }}分钟：{{ r.value == null ? r.reason : `${r.value.toFixed(2)}个百分点` }} · {{ clock(r.start) }}–{{ clock(r.end) }}</span>
    </div>
    <p class="text-xs text-muted-foreground">
      相对强弱仅供参考，不直接产生买卖信号。
    </p>
    <div
      v-if="snapshot.simulation?.references"
      class="text-xs text-muted-foreground"
    >
      <p>QQQ背景：{{ snapshot.simulation.references.background.label }} · 截至 {{ snapshot.simulation.references.background.asOf ?? '未知' }} · {{ snapshot.simulation.references.background.reason }}</p>
      <p>宏观日历：{{ snapshot.simulation.references.macroStatus }}</p>
      <p
        v-for="e in snapshot.simulation.references.macro"
        :key="e.title + e.at"
      >
        {{ e.title }} · {{ clock(e.at) }}（纽约） · {{ e.reason }} · 采集 {{ clock(e.asOf) }}
      </p>
    </div>
    <section aria-label="最近模拟进退场消息">
      <h3 class="font-medium">
        最近模拟进退场与持有变化 · 最新优先
      </h3>
      <p
        v-if="!importantEvents.length"
        class="text-sm text-muted-foreground"
      >
        暂无进退场或重要持有变化
      </p>
      <ul class="max-h-72 overflow-y-auto text-sm">
        <li
          v-for="e in importantEvents"
          :key="e.id"
          class="border-b py-2"
          data-testid="simulation-event"
        >
          模拟 · {{ e.symbol }} · {{ eventDirection(e) }} · {{ clock(e.at) }} · {{ e.reason }}
          <span v-if="e.trade?.estimated"> · 估算退出：价格时间 {{ clock(e.trade.exitPriceAt) }}；计划 {{ clock(e.trade.plannedExitAt) }}；实际处理 {{ clock(e.trade.exitAt) }}；{{ e.trade.anomaly }}</span>
        </li>
      </ul>
    </section>
    <p
      v-if="selected === 'all'"
      class="text-sm text-muted-foreground"
    >
      选择单标的可查看机会计划及相对强弱详情。
    </p>
    <details>
      <summary>行情与形态消息（{{ otherEvents.length }}）</summary>
      <ul class="max-h-72 overflow-y-auto text-sm">
        <li
          v-for="e in otherEvents"
          :key="e.id"
          class="border-b py-2"
        >
          模拟 · {{ e.symbol }} · {{ clock(e.at) }} · {{ e.reason }}
        </li>
      </ul>
    </details>
    <details>
      <summary>当日已完成模拟交易（{{ trades.length }}）</summary>
      <ul class="text-sm">
        <li
          v-for="t in trades"
          :key="t.id"
          class="border-b py-2"
        >
          {{ t.symbol }} · {{ t.side === 1 ? '做多' : '做空' }} · {{ opportunityKinds[t.kind] }} · {{ clock(t.entryAt) }}–{{ clock(t.exitAt) }} · {{ fmt(t.entryPrice) }} → {{ fmt(t.exitPrice) }} · 已实现 {{ pct(t.returnPct) }} · {{ t.exitReason }}{{ t.estimated ? '（估算退出）' : '' }}
        </li>
      </ul>
    </details>
    <details>
      <summary>全观察池当日逐笔统计 · 不代表组合收益</summary>
      <ul class="text-xs">
        <li
          v-for="s in snapshot.simulation?.statistics ?? []"
          :key="s.label"
          class="border-b py-2"
        >
          {{ s.label }} · {{ s.count }}笔 · 胜率 {{ pct(s.winRate) }} · 每笔平均 {{ pct(s.averageReturn) }} · 平均盈利 {{ pct(s.averageWin) }} / 亏损 {{ pct(s.averageLoss) }} · 平均持有 {{ s.averageDuration == null ? '—' : `${Math.round(s.averageDuration / 60)}分钟` }}
        </li>
      </ul>
    </details>
  </section>
</template>
