<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, ref, watch } from 'vue';
import { predictionApi, type PredictionEvent, type LiveData } from '@/api/predictionMarkets';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import { formatDateTimeInDisplayTimezone as dateTime } from '@/utils/format';
const PredictionHistory = defineAsyncComponent(() => import('./PredictionHistory.vue'));
const props = defineProps<{ event: PredictionEvent }>();
const data = ref<LiveData>();
const error = ref<ParsedApiError | null>(null);
const loading = ref(false);
const expanded = ref(false);
const history = ref<{ market: string; outcome: string }>();
let controller: AbortController | undefined;
let generation = 0;
async function load() {
  controller?.abort(); controller = new AbortController(); const token = ++generation;
  error.value = null; loading.value = true;
  try { const result = await predictionApi.live(props.event.eventId, controller.signal); if (token === generation) data.value = result; }
  catch (cause) { if (token === generation && !controller.signal.aborted) error.value = getParsedApiError(cause); }
  finally { if (token === generation) loading.value = false; }
}
watch(() => props.event.eventId, () => { data.value = undefined; history.value = undefined; expanded.value = false; void load(); }, { immediate: true });
onBeforeUnmount(() => { ++generation; controller?.abort(); });
const markets = computed(() => expanded.value ? data.value?.markets : data.value?.markets?.slice(0, 2));
</script>
<template>
  <article
    class="min-w-0 space-y-3 rounded-xl border bg-card p-4"
    data-testid="prediction-event-card"
  >
    <h3 class="break-words font-semibold">
      <a
        :href="event.url"
        target="_blank"
        rel="noopener noreferrer"
        class="hover:underline"
      >{{ event.title }} ↗</a>
    </h3>
    <p class="text-xs text-muted-foreground">
      截止 {{ event.endAt ? dateTime(event.endAt) : '未提供' }} · {{ (data?.closed ?? event.closed) ? '已关闭（不等于已结算）' : '未关闭' }}
    </p>
    <p class="text-xs text-muted-foreground">
      24h 成交额：{{ event.volume24H == null ? '暂无' : `$${event.volume24H.toLocaleString(undefined, { maximumFractionDigits: 0 })}` }}
    </p>
    <div class="border-t pt-3">
      <p
        v-if="loading"
        role="status"
      >
        正在读取选项与最新可用报价…
      </p>
      <AppApiErrorAlert
        v-else-if="error"
        :error="error"
        action-label="重试报价"
        @action="load"
      />
      <template v-else-if="data?.status === 'ready'">
        <p class="mb-2 text-xs text-muted-foreground">
          {{ data.stale ? '上游暂不可用 · 旧缓存' : '当前隐含概率' }} · 获取于 {{ data.fetchedAt ? dateTime(data.fetchedAt) : '暂无' }} · Gamma 结果报价 · 报价观察时间未提供
        </p>
        <section
          v-for="market in markets"
          :key="market.id"
          class="mb-3 space-y-2 rounded-lg border p-3"
        >
          <h4 class="text-sm font-medium">
            {{ market.question }}
          </h4>
          <p class="text-xs text-muted-foreground">
            {{ market.version ?? '协议未知' }} · {{ market.resolved ? '已结算，数值为结算结果' : market.closed ? '已关闭，数值非公告前概率' : '开放' }} · {{ market.endAt ? dateTime(market.endAt) : '截止时间未提供' }}
          </p>
          <div
            v-for="(outcome, index) in (expanded ? market.outcomes : market.outcomes.slice(0, 3))"
            :key="outcome.id ?? index"
            class="flex flex-wrap items-center gap-2 text-sm"
          >
            <span>{{ outcome.label }}：{{ outcome.probability == null ? '暂无' : `${(outcome.probability * 100).toFixed(1)}%` }}</span>
            <Button
              v-if="outcome.id"
              size="sm"
              variant="ghost"
              @click="history = history?.market === market.id && history?.outcome === outcome.id ? undefined : { market: market.id, outcome: outcome.id }"
            >
              {{ history?.market === market.id && history?.outcome === outcome.id ? '收起历史' : '变化与趋势' }}
            </Button>
          </div>
          <p
            v-if="!expanded && market.outcomes.length > 3"
            class="text-xs"
          >
            选项 3 / {{ market.outcomes.length }}
          </p>
        </section>
        <Button
          v-if="data.markets?.length"
          variant="outline"
          size="sm"
          @click="expanded = !expanded"
        >
          {{ expanded ? '折叠选项' : `展开全部问题与选项（${markets?.length} / ${data.markets.length} 个问题）` }}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          @click="load"
        >
          刷新报价
        </Button>
        <PredictionHistory
          v-if="history"
          :key="`${history.market}:${history.outcome}`"
          :event-id="event.eventId"
          :market-id="history.market"
          :outcome-id="history.outcome"
        />
      </template>
      <p
        v-else
        class="text-sm"
      >
        动态选项暂不可用，话题信息仍可查看。<Button
          variant="link"
          @click="load"
        >
          重试
        </Button>
      </p>
    </div>
  </article>
</template>
