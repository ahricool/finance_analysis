<script setup lang="ts">
import { computed, ref } from 'vue';
import type { IntradayOptionsSnapshot } from '@/api/intradayOptions';
import { useCurrentTime } from '@/composables/useCurrentTime';
import { clock, fmt, pct, opportunityKinds } from './labels';
import FieldSelect from '@/components/forms/FieldSelect.vue';
const props = defineProps<{ snapshot: IntradayOptionsSnapshot; disconnected: boolean }>();
const now = useCurrentTime(1000);
const selected = ref('SPY.US');
const row = computed(() => props.snapshot.items.find(r => r.symbol === selected.value));
const state = computed(() => row.value?.simulation);
const stale = computed(() => props.disconnected || !state.value || now.value.getTime() - Date.parse(state.value.calculatedAt) > 15000);
const position = computed(() => props.snapshot.simulation?.states.find(s => s.symbol === selected.value)?.position);
const remaining = computed(() => state.value?.cutoff ? Math.max(0, Math.ceil((Date.parse(state.value.cutoff) - now.value.getTime()) / 60000)) : null);
const events = computed(() => props.snapshot.simulation?.events.filter(e => e.symbol === selected.value) ?? []);
const trades = computed(() => props.snapshot.simulation?.trades.filter(t => t.symbol === selected.value) ?? []);
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
      :options="snapshot.items.map(r => ({ value: r.symbol, label: r.symbol }))"
    />
    <p class="text-sm">
      停止进场 {{ clock(state?.cutoff) }}（纽约） · {{ remaining === 0 ? '今日已停止进场' : remaining == null ? '交易日历暂无' : `距截止 ${remaining} 分钟` }}
    </p>
    <p class="text-xs text-muted-foreground">
      行情 {{ clock(state?.quoteTime) }} · 计算 {{ clock(state?.calculatedAt) }} · {{ disconnected ? '连接中断，仅显示历史状态' : '后台持续计算' }}
    </p>
    <div
      v-if="position"
      class="rounded border p-3 text-sm"
    >
      <strong>模拟持有{{ position.side === 1 ? '多' : '空' }}</strong> · 入场 {{ fmt(position.entryPrice) }} · 当前有效价 {{ fmt(state?.currentPrice) }}
      · 持有中 {{ pct(position.returnPct) }} · {{ duration(position.entryAt) }} 分钟
      <p>原始失效 {{ fmt(position.invalidation) }} · 保护位 {{ fmt(position.protection) }} · 目标 {{ fmt(position.target) }}</p>
      <p>下一步：等待保护位、目标、未推进超时或截止退出；持有中不再进场。</p>
      <p class="text-xs text-muted-foreground">
        估值价格截至 {{ clock(position.lastPriceAt) }}，失联期间保留旧估值。
      </p>
    </div>
    <p
      v-else
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
      <p>{{ stale ? '连接或计算延迟，当前入场资格未知' : p.executionReason }}</p>
      <p>首次确认 {{ clock(p.confirmedAt) }} · 年龄 {{ p.ageSeconds == null ? '—' : `${Math.floor(p.ageSeconds / 60)}分钟` }}</p>
      <p>入场区间 {{ fmt(p.entryLow) }}–{{ fmt(p.entryHigh) }} · 失效 {{ fmt(p.invalidation) }} · 目标 {{ fmt(p.target) }}（{{ p.targetSource }}）</p>
      <p>剩余空间 {{ fmt(p.remainingSpace) }} · 标的收益风险比 {{ fmt(p.rewardRisk) }}</p>
    </div>
    <p
      v-if="!state?.plans.length"
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
    <details>
      <summary>当日模拟事件（{{ events.length }}）· 最新优先</summary>
      <ul class="max-h-72 overflow-y-auto text-sm">
        <li
          v-for="e in events"
          :key="e.id"
          class="border-b py-2"
        >
          模拟 · {{ clock(e.at) }} · {{ e.reason }}
          <span v-if="e.trade?.estimated"> · 估算退出：价格时间 {{ clock(e.trade.exitPriceAt) }}；计划 {{ clock(e.trade.plannedExitAt) }}；实际处理 {{ clock(e.trade.exitAt) }}；{{ e.trade.anomaly }}</span>
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
          {{ t.side === 1 ? '做多' : '做空' }} · {{ opportunityKinds[t.kind] }} · {{ clock(t.entryAt) }}–{{ clock(t.exitAt) }} · {{ fmt(t.entryPrice) }} → {{ fmt(t.exitPrice) }} · 已实现 {{ pct(t.returnPct) }} · {{ t.exitReason }}{{ t.estimated ? '（估算退出）' : '' }}
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
