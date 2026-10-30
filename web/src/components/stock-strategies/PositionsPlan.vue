<script setup lang="ts">
import { formatRank } from '@/utils/rank';
import { computed, ref } from 'vue';
import type { Detail } from '@/api/stockStrategies';
import { positionMetrics, exitRows, scoreLabel } from '@/utils/stockStrategies';
import { formatPercent } from '@/utils/number';
import StockLink from '@/components/stocks/StockLink.vue';
import { Button } from '@/components/ui/button';
const props = defineProps<{ detail: Detail }>();
const all = ref(false);
const day = computed(() => props.detail.latest);
const plan = computed(() => day.value?.payload.plan);
const overdue = computed(() => !!plan.value && !!props.detail.expectedDate && plan.value.executionDate <= props.detail.expectedDate);
const positions = computed(() => Object.entries(day.value?.payload.positions ?? {}).map(([code, pos]) => ({ code, pos, ...positionMetrics(pos, day.value?.nav) })));
const exits = computed(() => exitRows(day.value));
const pct = (v: number | null | undefined, signed = false) => formatPercent(v, { digits: 2, signed });
const num = (v: number | null | undefined) => v == null || !Number.isFinite(v) ? '—' : v.toLocaleString('zh-CN', { maximumFractionDigits: 4 });
const tone = (v: number | null) => v == null || v === 0 ? '' : v > 0 ? 'text-market-up' : 'text-market-down';
</script>
<template>
  <div class="grid min-w-0 gap-5 xl:grid-cols-2">
    <section class="min-w-0 rounded-lg border p-4">
      <h2 class="font-semibold">
        当前模拟持仓
      </h2>
      <p class="my-2 text-xs text-muted-foreground">
        浮动盈亏仅反映当前持仓，不等于策略完整收益。金额单位：{{ detail.market === 'CN' ? 'CNY' : 'USD' }}。
      </p>
      <p
        v-if="!day"
        class="py-6 text-muted-foreground"
      >
        尚无成功结算，暂不能判断持仓。
      </p>
      <p
        v-else-if="!positions.length"
        class="py-6 text-muted-foreground"
      >
        当前空仓 · 已结算账户无持仓
      </p>
      <article
        v-for="p in positions"
        :key="p.code"
        class="my-3 rounded-lg border p-3"
        data-testid="strategy-position"
      >
        <StockLink
          :code="p.code"
          :name="p.pos.name"
          :market="detail.market"
        />
        <dl class="mt-3 grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt class="text-muted-foreground">
              市值 / 净值占比
            </dt><dd>{{ num(p.value) }} / {{ pct(p.weight) }}</dd>
          </div>
          <div>
            <dt class="text-muted-foreground">
              浮动盈亏 / 成本收益率
            </dt><dd :class="tone(p.pnl)">
              {{ num(p.pnl) }} / {{ pct(p.pnlPct, true) }}
            </dd>
          </div>
          <div>
            <dt class="text-muted-foreground">
              股数 / 单股成本
            </dt><dd>{{ num(p.pos.quantity) }} / {{ num(p.pos.entryPrice) }}</dd>
          </div>
          <div>
            <dt class="text-muted-foreground">
              估值 / 估值日期
            </dt><dd>{{ num(p.pos.mark) }} / {{ p.pos.markDate || '未知' }}</dd>
          </div>
          <div v-if="p.stopDistance != null">
            <dt class="text-muted-foreground">
              ATR线 / 距离
            </dt><dd>{{ num(p.pos.stop) }} / {{ pct(p.stopDistance, true) }}</dd>
          </div>
        </dl>
        <p
          v-if="!p.pos.markDate || p.pos.markDate < day!.tradeDate || day?.payload.staleCodes.includes(p.code)"
          class="mt-2 text-sm text-destructive"
        >
          估值过期或缺失：沿用最后有效估值，非当日完整行情。
        </p>
        <p
          v-if="p.pos.pendingExit.length"
          class="mt-2 text-sm text-destructive"
        >
          待退出（此前卖出受阻）：{{ p.pos.pendingExit.join('；') }}
        </p>
        <p
          v-else-if="plan?.exits[p.code]?.length"
          class="mt-2 text-sm"
        >
          已计划退出，尚未模拟成交：{{ plan.exits[p.code]!.join('；') }}
        </p>
      </article>
      <p class="text-xs text-muted-foreground">
        市值=股数×估值；浮盈=股数×(估值−成本)；距ATR线=(估值−止损线)/估值。ATR按收盘规则判断，通常下一开盘才模拟退出，不保证盘中止损。
      </p>
      <p
        v-for="warning in day?.payload.warnings ?? []"
        :key="warning"
        class="mt-2 text-sm text-destructive"
      >
        {{ warning }}
      </p>
    </section>
    <section
      class="min-w-0 rounded-lg border p-4"
      data-testid="strategy-plan"
    >
      <h2 class="font-semibold">
        {{ day?.payload.nextIsHistorical ? '历史补算计划（非当前待执行）' : overdue ? '此前冻结计划（等待结算）' : '下一交易日模拟计划' }}
      </h2>
      <p class="mt-2 text-sm text-muted-foreground">
        系统在下一交易日盘后结算时，按该日开盘价模拟执行此前冻结的计划。
      </p>
      <template v-if="plan">
        <p
          v-if="day?.payload.nextIsHistorical"
          class="mt-3 text-sm text-destructive"
        >
          历史补算计划，生成时该开盘已过去，请勿作为当前待执行计划。
        </p>
        <p
          v-if="overdue"
          class="mt-3 text-sm text-amber-700 dark:text-amber-400"
        >
          计划执行日期已不晚于参考交易日 {{ detail.expectedDate }}，尚未记录该日成功结算；这不是未来交易日的新计划。
        </p>
        <h3 class="mt-4 font-medium">
          执行概况
        </h3>
        <dl class="mt-2 grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt class="text-muted-foreground">
              信号日期
            </dt><dd>{{ plan.signalDate }}</dd>
          </div>
          <div>
            <dt class="text-muted-foreground">
              模拟成交日期
            </dt><dd>{{ plan.executionDate }}</dd>
          </div>
          <div>
            <dt class="text-muted-foreground">
              持仓上限 / 当前持仓
            </dt><dd>{{ detail.strategy.slots }} / {{ positions.length }}</dd>
          </div>
          <div>
            <dt class="text-muted-foreground">
              计划退出 / 暂停新增
            </dt><dd>{{ exits.length }} / {{ plan.status === 'PAUSED' ? '是' : '否' }}</dd>
          </div>
        </dl>
        <p
          v-if="positions.length >= detail.strategy.slots"
          class="mt-3 text-sm"
        >
          已满仓；候选存在也不代表新增买入。计划卖出尚未释放仓位或资金。
        </p>
        <p
          v-if="plan.status === 'PAUSED'"
          class="mt-3 text-sm text-destructive"
        >
          暂停新增：剩余 {{ day?.payload.pauseRemaining }} 个开盘；候选不代表仍会买入，恢复还须满足策略规则。
        </p>
        <p
          v-if="exits.length"
          class="mt-3 text-sm"
        >
          存在待退出持仓：先尝试卖出，受阻则保留持仓与原因，不假设资金已释放。
        </p>
        <h3 class="mt-4 font-medium">
          计划卖出 · {{ exits.length }}
        </h3>
        <p
          v-if="!exits.length"
          class="mt-2 text-sm text-muted-foreground"
        >
          无计划卖出。
        </p>
        <div
          v-for="[code, reasons] in exits"
          :key="code"
          class="mt-2 rounded border p-2 text-sm"
        >
          <StockLink
            :code="code"
            :name="day?.payload.positions[code]?.name"
            :market="detail.market"
          />
          <p>待卖出 · {{ reasons.join('；') }}</p>
        </div>
        <h3 class="mt-4 font-medium">
          买入候选 · 候选内排名 · 共 {{ plan.candidates.length }} 个（非买入清单）
        </h3>
        <p class="mt-2 text-sm text-muted-foreground">
          按排名依次检查，满足条件才买入，仓位满后停止。跳过已持有、当天已交易、存在退出指令或不可成交的标的；还须允许新增、有实际空位且现金足够。候选仅属于指定执行日，未成交退出持续保留。
        </p>
        <p
          v-if="!plan.candidates.length"
          class="mt-3 text-sm text-muted-foreground"
        >
          无新增候选。
        </p>
        <ol class="mt-3 space-y-2">
          <li
            v-for="(c, index) in (all ? plan.candidates : plan.candidates.slice(0, 5))"
            :key="c.code"
            class="rounded border p-2 text-sm"
            data-testid="strategy-candidate"
          >
            <div class="flex items-center gap-2">
              <span>{{ formatRank(index + 1, plan.candidates.length) }}</span><StockLink
                :code="c.code"
                :name="c.name"
                :market="detail.market"
              />
            </div>
            <p class="mt-1 break-words text-xs text-muted-foreground">
              {{ scoreLabel(detail.strategy, c) }}：{{ num(c.score) }} · 信号收盘价 {{ num(c.signalClose) }}
            </p>
          </li>
        </ol>
        <Button
          v-if="plan.candidates.length > 5"
          variant="outline"
          class="mt-3"
          @click="all = !all"
        >
          {{ all ? '收起候选' : `查看全部${plan.candidates.length}个候选` }}
        </Button>
        <p class="mt-3 text-xs text-muted-foreground">
          保留原候选顺序，评分仅按本策略定义解读，不跨策略比较；混合策略股票优先，ETF补位，二者评分不同。隔夜跳空会改变成交价及数量，不额外取消计划。有开盘价不代表实盘可全量成交。
        </p>
      </template>
      <p
        v-else
        class="py-8 text-muted-foreground"
      >
        尚未生成计划，等待首次成功结算。
      </p>
    </section>
  </div>
</template>
