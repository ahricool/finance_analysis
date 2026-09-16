<script setup lang="ts">
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { trendFollowingApi } from '@/api/trendFollowing';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import type { TrendMarket, TrendTransitionsResponse, TransitionDirection } from '@/types/trendFollowing';
import { describeTrendStateChange, TREND_TRANSITION_RANGES } from '@/utils/trendStateChange';

const props = defineProps<{ market: TrendMarket; asOf?: string; includePreview: boolean; refreshKey: number }>();
const emit = defineEmits<{ select: [value: { code: string; tradeDate: string; preview: boolean }] }>();
const days = ref<1 | 3 | 5>(3);
const direction = ref<TransitionDirection>('all');
const directions: Array<{ value: TransitionDirection; label: string }> = [
  { value: 'all', label: '全部' }, { value: 'strengthening', label: '转强' }, { value: 'deteriorating', label: '转弱' },
];
const data = shallowRef<TrendTransitionsResponse | null>(null);
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(false);
let requestId = 0;
async function load() {
  const id = ++requestId;
  data.value = null;
  error.value = null;
  loading.value = true;
  try {
    const result = await trendFollowingApi.transitions(props.market, days.value, direction.value, props.asOf, props.includePreview);
    if (id === requestId) data.value = result;
  } catch (reason) {
    if (id === requestId) error.value = getParsedApiError(reason);
  } finally {
    if (id === requestId) loading.value = false;
  }
}
watch(() => [props.market, props.asOf, props.includePreview, props.refreshKey, days.value, direction.value],
  () => void load(), { immediate: true });
onBeforeUnmount(() => { requestId++; });
</script>

<template>
  <section
    class="rounded-xl border bg-card p-4 text-card-foreground"
    data-testid="trend-transitions"
    :aria-busy="loading"
  >
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="font-semibold">
          趋势状态变更
        </h3>
        <p class="mt-1 text-xs text-muted-foreground">
          展示最近交易快照中 State 发生关键变化的股票。转强表示趋势确认或恢复，转弱表示趋势弱化或破坏。
        </p>
      </div>
      <div class="flex gap-4">
        <div
          class="flex gap-1"
          aria-label="状态变化方向"
        >
          <Button
            v-for="item in directions"
            :key="item.value"
            size="sm"
            :variant="direction === item.value ? 'secondary' : 'ghost'"
            :aria-pressed="direction === item.value"
            @click="direction = item.value"
          >
            {{ item.label }}
          </Button>
        </div>
        <div
          class="flex gap-1"
          aria-label="状态变化时间范围"
        >
          <Button
            v-for="range in TREND_TRANSITION_RANGES"
            :key="range.days"
            size="sm"
            :variant="days === range.days ? 'secondary' : 'ghost'"
            :aria-pressed="days === range.days"
            @click="days = range.days"
          >
            {{ range.label }}
          </Button>
        </div>
      </div>
    </div>
    <p
      v-if="loading"
      class="py-8 text-center text-sm text-muted-foreground"
    >
      正在加载状态变化…
    </p>
    <AppApiErrorAlert
      v-else-if="error"
      class="mt-4"
      :error="error"
      action-label="重试状态变化"
      @action="load"
      @dismiss="error = null"
    />
    <template v-else>
      <div
        v-if="data?.items?.length"
        class="mt-4 divide-y"
      >
        <button
          v-for="item in data.items"
          :key="`${item.tradeDate}-${item.code}`"
          class="grid w-full grid-cols-[24px_minmax(140px,1fr)_minmax(280px,1.6fr)_minmax(150px,1fr)_140px] items-center gap-3 rounded px-2 py-3 text-left text-sm hover:bg-muted/60 focus-visible:outline-2 focus-visible:outline-ring"
          data-testid="trend-transition"
          @click="emit('select', { code: item.code, tradeDate: item.tradeDate, preview: item.isPreview })"
        >
          <span
            class="text-lg"
            :class="item.direction === 'strengthening' ? 'text-emerald-700 dark:text-emerald-400' : 'text-orange-700 dark:text-orange-400'"
          >{{ item.direction === 'strengthening' ? '↑' : '↓' }}<span class="sr-only">{{ item.direction === 'strengthening' ? '转强' : '转弱' }}</span></span>
          <span class="min-w-0"><strong class="block truncate font-medium">{{ item.name }}</strong><span class="font-mono text-xs text-muted-foreground">{{ item.code }}</span></span>
          <span>
            <strong class="block">{{ describeTrendStateChange(item.previousState, item.currentState) }}</strong>
            <span class="text-xs text-muted-foreground">{{ item.previousState }} → {{ item.currentState }}</span>
          </span>
          <span class="text-xs tabular-nums text-muted-foreground">Rank #{{ item.previousRank }} → #{{ item.currentRank }}<span class="ml-2">({{ item.rankDelta > 0 ? '+' : '' }}{{ item.rankDelta }})</span></span>
          <span class="text-right text-xs text-muted-foreground">{{ item.tradeDate }}<span
            v-if="item.isPreview"
            class="ml-1 rounded border border-amber-500/50 px-1 text-amber-700 dark:text-amber-400"
          >Preview</span></span>
        </button>
      </div>
      <p
        v-else
        class="py-8 text-center text-sm text-muted-foreground"
      >
        所选范围暂无重要状态变化
      </p>
      <p
        v-for="warning in data?.warnings"
        :key="warning"
        class="mt-2 text-xs text-muted-foreground"
      >
        {{ warning }}
      </p>
    </template>
  </section>
</template>
