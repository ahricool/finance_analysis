<script setup lang="ts">
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { trendFollowingApi } from '@/api/trendFollowing';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import type { TrendMarket, TrendTransitionsResponse, TransitionDirection } from '@/types/trendFollowing';

const props = defineProps<{ market: TrendMarket; asOf?: string; includePreview: boolean; refreshKey: number }>();
const emit = defineEmits<{ select: [value: { code: string; tradeDate: string; preview: boolean }] }>();
const days = ref<1 | 3 | 5>(3);
const direction = ref<TransitionDirection>('all');
const directions: Array<{ value: TransitionDirection; label: string }> = [
  { value: 'all', label: '全部' }, { value: 'strengthening', label: '转强' }, { value: 'deteriorating', label: '转弱' },
];
const ranges = [1, 3, 5] as const;
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
          最近状态变化
        </h3>
        <p class="mt-1 text-xs text-muted-foreground">
          最近 {{ days }} 个正式 Snapshot session{{ data?.previewDate ? ' + Preview' : '' }} · 最多 20 条 · 日期、重要性、Rank 排序
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
            v-for="range in ranges"
            :key="range"
            size="sm"
            :variant="days === range ? 'secondary' : 'ghost'"
            :aria-pressed="days === range"
            @click="days = range"
          >
            {{ range }}D
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
          class="grid w-full grid-cols-[24px_minmax(140px,1fr)_minmax(240px,1.3fr)_minmax(150px,1fr)_140px] items-center gap-3 rounded px-2 py-3 text-left text-sm hover:bg-muted/60 focus-visible:outline-2 focus-visible:outline-ring"
          data-testid="trend-transition"
          @click="emit('select', { code: item.code, tradeDate: item.tradeDate, preview: item.isPreview })"
        >
          <span
            class="text-lg"
            :class="item.direction === 'strengthening' ? 'text-emerald-700 dark:text-emerald-400' : 'text-orange-700 dark:text-orange-400'"
          >{{ item.direction === 'strengthening' ? '↑' : '↓' }}<span class="sr-only">{{ item.direction === 'strengthening' ? '转强' : '转弱' }}</span></span>
          <span class="min-w-0"><strong class="block truncate font-medium">{{ item.name }}</strong><span class="font-mono text-xs text-muted-foreground">{{ item.code }}</span></span>
          <span class="text-xs">{{ item.previousState }} <span class="px-1 text-muted-foreground">→</span> {{ item.currentState }}</span>
          <span class="text-xs tabular-nums">Rank #{{ item.previousRank }} → #{{ item.currentRank }}<span class="ml-2 text-muted-foreground">({{ item.rankDelta > 0 ? '+' : '' }}{{ item.rankDelta }})</span></span>
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
