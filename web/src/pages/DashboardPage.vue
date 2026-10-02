<script setup lang="ts">
import { computed, ref } from 'vue';
import { RouterLink } from 'vue-router';
import { ArrowUpRight, Bitcoin } from 'lucide-vue-next';
import { useMarketDashboard } from '@/composables/useMarketDashboard';
import { useCurrentTime } from '@/composables/useCurrentTime';
import MarketStructureCard from '@/components/dashboard/MarketStructureCard.vue';
import DashboardState from '@/components/dashboard/DashboardState.vue';
import StrategyChanges from '@/components/dashboard/StrategyChanges.vue';
import { feedSummary, regimeTone, upcomingEvents } from '@/components/dashboard/dashboardFormat';
import BilingualLabel from '@/components/app/BilingualLabel.vue';
import BilingualEnum from '@/components/app/BilingualEnum.vue';
import { importanceNames, kindLabel, marketLabel, sessionLabel } from '@/components/timeline/timelineFormat';
import { formatDateTimeInDisplayTimezone, getDisplayTimezone } from '@/utils/format';
import { formatScore } from '@/utils/quant';

const { markets, latest, upcoming, btc } = useMarketDashboard();
const now = useCurrentTime();
const strategyMarket = ref('CN');
const strategyMarkets = computed(() => markets.filter(entry => entry.market === strategyMarket.value));
const nextEvents = computed(() => upcomingEvents(upcoming.data?.items ?? [], now.value));
const btcPrice = computed(() => btc.data?.strategy?.price);
const number = (value: string | undefined) => value && Number.isFinite(Number(value))
  ? Number(value).toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—';
</script>

<template>
  <div
    class="space-y-7 py-6"
    data-testid="market-dashboard"
  >
    <header class="flex items-end justify-between gap-4">
      <div class="min-w-0">
        <h1 class="text-3xl font-semibold tracking-tight">
          市场动态
        </h1>
        <p class="mt-1 text-xs font-normal tracking-wide text-muted-foreground sm:text-sm">
          Market Intelligence
        </p>
        <p class="mt-1.5 text-sm text-muted-foreground">
          市场状态、重要事件与策略变化的实时概览
        </p>
      </div>
      <div class="shrink-0 text-right text-xs leading-6 text-muted-foreground">
        <p>{{ getDisplayTimezone() === 'Asia/Shanghai' ? '北京时间' : '美东时间' }}</p>
        <time class="tabular-nums">{{ formatDateTimeInDisplayTimezone(now.toISOString()) }}</time>
      </div>
    </header>

    <section
      aria-label="Market Structure"
      class="overflow-hidden rounded-xl border border-border/80 bg-card shadow-xs transition-shadow hover:shadow-sm"
    >
      <h2 class="border-b border-border/70 bg-muted/30 px-6 py-3.5 text-sm font-semibold tracking-wide">
        <BilingualLabel label="marketStructure" />
      </h2>
      <div class="grid grid-cols-1 divide-y md:grid-cols-2 md:divide-x md:divide-y-0">
        <div
          v-for="entry in markets"
          :key="entry.market"
          class="p-6"
        >
          <DashboardState
            :state="entry.structure"
            :empty="!entry.structure.data"
            empty-message="暂无今日市场结构快照（非交易日或尚未生成）"
            @retry="entry.structure.refresh"
          >
            <MarketStructureCard
              v-if="entry.structure.data"
              :snapshot="entry.structure.data"
            />
          </DashboardState>
          <div
            v-if="entry.trend.data?.features?.lifecycleCounts"
            class="mt-4 border-t pt-3 text-xs text-muted-foreground"
          >
            <p class="mb-2">
              趋势概览 · {{ entry.trend.data.tradeDate }}
            </p>
            <div class="flex flex-wrap gap-x-4 gap-y-2">
              <span
                v-for="(count, stage) in entry.trend.data.features.lifecycleCounts"
                :key="stage"
                class="inline-flex items-baseline gap-1"
              >
                <BilingualEnum
                  :value="String(stage)"
                  size="inline"
                />
                <strong class="text-foreground">{{ count }}</strong>
              </span>
            </div>
            <p class="mt-2 inline-flex flex-wrap items-baseline gap-1">
              <BilingualLabel label="highFragilityTrends" compact />
              <span>{{ entry.trend.data.features.highFragilityCount ?? '—' }}</span>
            </p>
          </div>
        </div>
      </div>
    </section>

    <section
      class="rounded-xl border bg-muted/20"
      aria-label="市场环境"
    >
      <div class="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3 sm:px-6">
        <h2 class="text-sm font-semibold">
          <BilingualLabel label="marketRegimeSection" />
        </h2>
        <span class="text-xs text-muted-foreground">趋势跟踪 · 最新交易日</span>
      </div>
      <div class="grid grid-cols-1 divide-y lg:grid-cols-2 lg:divide-x lg:divide-y-0">
        <div
          v-for="entry in markets"
          :key="entry.market"
          class="min-w-0 px-4 py-5 sm:px-7"
        >
          <DashboardState
            :state="entry.trend"
            :empty="!entry.trend.data"
            @retry="entry.trend.refresh"
          >
            <div class="mb-4 flex flex-wrap justify-between gap-2 text-sm">
              <strong>{{ marketLabel(entry.market) }}</strong><span class="text-xs tabular-nums text-muted-foreground">数据日期 {{ entry.trend.data?.tradeDate }}</span>
            </div>
            <div class="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end sm:gap-4">
              <BilingualEnum
                :value="entry.trend.data?.marketRegime"
                size="large"
                :class="regimeTone(entry.trend.data?.marketRegime)"
              />
              <div class="min-w-0 sm:text-right">
                <p class="text-4xl font-light leading-none tracking-tight tabular-nums sm:text-5xl">
                  {{ formatScore(entry.trend.data?.marketScore, 1) }}
                </p>
                <p class="mt-2 text-[10px] text-muted-foreground">
                  <BilingualLabel
                    label="marketScore"
                    compact
                  /> / 100
                </p>
              </div>
            </div>
            <div class="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground">
              <span
                v-for="(label, key) in { trend: '趋势', breadth: '宽度', risk: '风险' }"
                :key="key"
              >
                {{ label }} <strong class="ml-1 text-foreground">{{ formatScore(entry.trend.data?.scoreBreakdown?.[key], 0) }}</strong>
              </span>
            </div>
          </DashboardState>
        </div>
      </div>
    </section>

    <section
      aria-label="策略变化"
      class="rounded-xl bg-muted/25 px-5 py-4"
    >
      <div class="flex items-center justify-between gap-3">
        <h2 class="text-lg font-semibold">
          <BilingualLabel label="strategyChanges" />
        </h2>
        <div
          class="flex gap-1"
          aria-label="策略市场"
        >
          <button
            v-for="market in ['CN', 'US']"
            :key="market"
            class="rounded-md px-2.5 py-1 text-xs"
            :class="strategyMarket === market ? 'bg-foreground text-background' : 'text-muted-foreground hover:bg-muted'"
            :aria-pressed="strategyMarket === market"
            @click="strategyMarket = market"
          >
            {{ marketLabel(market) }}
          </button>
        </div>
      </div>
      <p class="mt-1 text-xs text-muted-foreground">
        <BilingualLabel
          label="whatsChanged"
          inline
        /> · 最新交易日与前一交易日对比
      </p>
      <div
        v-for="entry in strategyMarkets"
        :key="entry.market"
        class="mt-5 space-y-5"
      >
        <div class="border-t pt-4">
          <RouterLink
            :to="{ path: '/research/etf-rotation', query: { market: entry.market } }"
            class="mb-3 flex items-center justify-between text-sm font-semibold"
          >
            {{ marketLabel(entry.market) }} · ETF 动量轮动 <ArrowUpRight class="size-4" />
          </RouterLink>
          <DashboardState
            :state="entry.etf"
            :empty="!entry.etf.data"
            @retry="entry.etf.refresh"
          >
            <StrategyChanges :etf="entry.etf.data" />
          </DashboardState>
        </div>
        <div class="border-t pt-4">
          <RouterLink
            :to="{ path: '/research/trend-following', query: { market: entry.market } }"
            class="mb-3 flex items-center justify-between text-sm font-semibold"
          >
            {{ marketLabel(entry.market) }} · 趋势跟踪 <ArrowUpRight class="size-4" />
          </RouterLink>
          <DashboardState
            :state="entry.trend"
            :empty="!entry.trend.data"
            @retry="entry.trend.refresh"
          >
            <StrategyChanges :trend="entry.trend.data" />
          </DashboardState>
        </div>
      </div>
    </section>

    <div class="grid grid-cols-1 items-start gap-8 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <section
        aria-label="Latest"
        class="min-w-0"
      >
        <div class="mb-3 flex items-baseline justify-between gap-3 border-b pb-3">
          <h2 class="text-lg font-semibold">
            <BilingualLabel
              zh="最新动态"
              en="Latest"
            />
          </h2>
          <span class="shrink-0 text-xs text-muted-foreground">按事件时间倒序 · 含未来事件</span>
        </div>
        <DashboardState
          :state="latest"
          :empty="!latest.data?.items.length"
          @retry="latest.refresh"
        >
          <div
            class="max-h-[480px] overflow-y-auto pr-2"
            tabindex="0"
            aria-label="最新动态列表"
          >
            <RouterLink
              v-for="item in latest.data?.items"
              :key="item.id"
              to="/timeline"
              class="group block border-b px-2 py-4 transition-colors hover:bg-muted/40"
              data-testid="dashboard-feed-item"
            >
              <div class="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                <span class="min-w-0 truncate">{{ formatDateTimeInDisplayTimezone(item.eventTime) }} · {{ kindLabel(item) }} · {{ marketLabel(item.market) }}</span>
                <span
                  class="shrink-0"
                  :class="item.importance === 'critical' ? 'text-destructive' : 'text-muted-foreground'"
                >{{ item.importanceScore ? `${item.importanceScore}/10` : importanceNames[item.importance] }}</span>
              </div>
              <h3 class="mt-2 truncate text-base font-semibold leading-snug group-hover:text-primary">
                {{ item.title }}
              </h3>
              <p
                v-if="feedSummary(item)"
                class="mt-1 truncate text-sm text-muted-foreground"
              >
                {{ feedSummary(item) }}
              </p>
              <div
                v-if="item.relatedSymbols.length || item.impact"
                class="mt-2 flex gap-3 text-xs"
              >
                <span
                  v-if="item.impact"
                  :class="item.impact === 'bullish' ? 'text-market-up' : item.impact === 'bearish' ? 'text-market-down' : 'text-muted-foreground'"
                >{{ item.impact === 'bullish' ? '利多' : item.impact === 'bearish' ? '利空' : '中性' }}</span>
                <span class="text-muted-foreground">{{ item.relatedSymbols.slice(0, 4).join(' · ') }}</span>
              </div>
            </RouterLink>
          </div>
        </DashboardState>
        <RouterLink
          to="/timeline"
          class="mt-4 inline-flex items-center gap-1 text-sm font-medium"
        >
          查看全部动态 <ArrowUpRight class="size-4" />
        </RouterLink>
      </section>

      <section
        aria-label="What's Next"
        class="min-w-0 border-t pt-5"
      >
        <div class="flex items-baseline justify-between gap-3">
          <h2 class="text-lg font-semibold">
            <BilingualLabel
              zh="接下来"
              en="What's Next"
            />
          </h2><span class="shrink-0 text-xs text-muted-foreground">未来7天 · 时间倒序</span>
        </div>
        <DashboardState
          :state="upcoming"
          @retry="upcoming.refresh"
        >
          <p
            v-if="!nextEvents.length"
            class="py-6 text-sm text-muted-foreground"
          >
            未来7天暂无财报或宏观事件
          </p>
          <RouterLink
            v-for="item in nextEvents"
            :key="item.id"
            to="/timeline"
            class="block border-b py-3 hover:bg-muted/30"
          >
            <div class="flex justify-between gap-3 text-xs text-muted-foreground">
              <span class="min-w-0 truncate">{{ formatDateTimeInDisplayTimezone(item.eventTime) }} {{ sessionLabel(item.detailPayload.marketSession) }}</span><span
                class="shrink-0"
                :class="item.importance === 'critical' ? 'text-destructive' : ''"
              >{{ importanceNames[item.importance] }}</span>
            </div>
            <p class="mt-1.5 truncate text-sm font-medium">
              {{ item.title }}
            </p>
          </RouterLink>
        </DashboardState>
        <RouterLink
          to="/timeline"
          class="mt-4 inline-flex items-center gap-1 text-sm font-medium"
        >
          查看事件时间线 <ArrowUpRight class="size-4" />
        </RouterLink>
      </section>
    </div>

    <section
      aria-label="Model Pulse"
      class="min-w-0 border-t pt-5"
    >
      <h2 class="text-lg font-semibold">
        <BilingualLabel
          zh="模型研究信号"
          en="Model Pulse"
        />
      </h2>
      <div class="mt-4 grid grid-cols-1 divide-y md:grid-cols-2 md:divide-x md:divide-y-0">
        <div
          v-for="entry in markets"
          :key="entry.market"
          class="pr-5 last:pl-5 last:pr-0"
        >
          <RouterLink
            :to="{ path: '/research/quant', query: { market: entry.market } }"
            class="flex items-center justify-between text-sm font-semibold"
          >
            {{ marketLabel(entry.market) }} · Quant <ArrowUpRight class="size-4" />
          </RouterLink>
          <DashboardState
            :state="entry.signals"
            :empty="!entry.signals.data?.items.length"
            @retry="entry.signals.refresh"
          >
            <p class="my-3 text-xs text-muted-foreground">
              {{ entry.signals.data?.tradeDate }} · Research Signal · Top 3
            </p>
            <RouterLink
              v-for="(item, index) in entry.signals.data?.items.slice(0, 3)"
              :key="item.code"
              :to="{ path: '/research/quant', query: { market: entry.market } }"
              class="flex items-center gap-3 py-2 text-sm"
            >
              <span class="text-xs tabular-nums text-muted-foreground">0{{ index + 1 }}</span><span class="min-w-0 flex-1 truncate font-medium">{{ item.name || item.code }}</span><span class="tabular-nums">{{ formatScore(item.finalScore) }}</span>
            </RouterLink>
          </DashboardState>
        </div>
      </div>
      <div class="mt-5 rounded-lg border px-5 py-4">
        <RouterLink
          to="/crypto/btc"
          class="flex items-center gap-2 text-sm font-semibold"
        >
          <Bitcoin class="size-4" /> BTCUSDT <span class="ml-auto text-xs font-normal text-muted-foreground">24 / 7</span><ArrowUpRight class="size-4" />
        </RouterLink>
        <DashboardState
          :state="btc"
          :empty="!btc.data"
          @retry="btc.refresh"
        >
          <div class="mt-4 flex items-end justify-between gap-4">
            <div>
              <p class="text-3xl font-semibold tabular-nums">
                {{ number(btcPrice) }} <span class="text-xs font-normal text-muted-foreground">USDT</span>
              </p><p class="mt-2 text-xs text-muted-foreground">
                策略评估价格 · 每 15 分钟收盘后更新
              </p>
            </div>
            <div class="text-right">
              <p
                class="text-xl font-semibold"
                :class="regimeTone(btc.data?.strategy?.regime)"
              >
                {{ btc.data?.strategy?.regime ?? '等待数据' }}
              </p><p class="mt-2 text-xs">
                {{ btc.data?.strategy?.setup ?? '—' }} · {{ btc.data?.strategy?.action ?? '—' }} · {{ btc.data?.strategy?.positionState ?? '—' }}
              </p>
            </div>
          </div>
        </DashboardState>
      </div>
    </section>
  </div>
</template>
