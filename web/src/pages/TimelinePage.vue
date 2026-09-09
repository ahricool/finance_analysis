<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { parseDate } from '@internationalized/date';
import { storeToRefs } from 'pinia';
import { timelineApi, type Importance, type TimelineItem, type TimelineQuery, type TimelineTab } from '@/api/timeline';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import LoadingButton from '@/components/app/LoadingButton.vue';
import TimelineAnalysisCard from '@/components/timeline/TimelineAnalysisCard.vue';
import TimelineEarningsCard from '@/components/timeline/TimelineEarningsCard.vue';
import TimelineEventDetail from '@/components/timeline/TimelineEventDetail.vue';
import TimelineMacroCard from '@/components/timeline/TimelineMacroCard.vue';
import TimelineNewsCard from '@/components/timeline/TimelineNewsCard.vue';
import { dayHeading, dayKey, importanceNames, kindLabel, marketLabel, tabQuery } from '@/components/timeline/timelineFormat';
import { Dialog, DialogDescription, DialogHeader, DialogScrollContent, DialogTitle } from '@/components/ui/dialog';
import { useTimezoneStore } from '@/stores/timezoneStore';
import { formatDateTimeInDisplayTimezone, getTodayInDisplayTimezone } from '@/utils/format';
import { renderMarkdownToHtml } from '@/utils/renderMarkdown';

const { displayTimezone } = storeToRefs(useTimezoneStore());
const markets = [{ value: '', label: '全部市场' }, { value: 'CN', label: 'A股' }, { value: 'US', label: '美股' }] as const;
const tabs = [
  { value: 'all', label: '全部' }, { value: 'earnings', label: '财报' }, { value: 'macro', label: '宏观' },
  { value: 'news', label: '新闻' }, { value: 'analysis', label: '市场分析' },
] as const;
const cards = { earnings: TimelineEarningsCard, macro: TimelineMacroCard, news: TimelineNewsCard, analysis: TimelineAnalysisCard };

const market = ref('');
const tab = ref<TimelineTab>('all');
type DatePreset = 'today' | '7d' | '14d' | '30d' | 'custom';
const presets = [
  { value: 'today', days: 0, label: '今天' }, { value: '7d', days: 7, label: '未来7天' },
  { value: '14d', days: 14, label: '未来14天' }, { value: '30d', days: 30, label: '未来30天' },
] as const;
const preset = ref<DatePreset>('today');
const endDate = ref(getTodayInDisplayTimezone());
const importance = ref<Importance | ''>('');
function selectPreset(value: Exclude<DatePreset, 'custom'>) {
  preset.value = value;
  const days = presets.find(option => option.value === value)!.days;
  endDate.value = parseDate(getTodayInDisplayTimezone()).add({ days }).toString();
}
function selectCustomDate(value: string) {
  if (!value) return;
  preset.value = 'custom';
  endDate.value = value;
}
watch(displayTimezone, () => {
  if (preset.value !== 'custom') selectPreset(preset.value);
});
const items = ref<TimelineItem[]>([]);
const total = ref(0);
const nextCursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const detail = ref<TimelineItem | null>(null);

const query = computed<TimelineQuery>(() => ({
  ...tabQuery[tab.value],
  end_date: endDate.value,
  market: market.value || undefined,
  importance: importance.value || undefined,
}));

/** The API already returns a stable event_time DESC page; never re-sort on the client. */
const groups = computed(() => {
  const result: { key: string; items: TimelineItem[] }[] = [];
  for (const item of items.value) {
    const key = dayKey(item.eventTime);
    if (result.at(-1)?.key !== key) result.push({ key, items: [] });
    result.at(-1)!.items.push(item);
  }
  return result;
});

function cardFor(item: TimelineItem) {
  if (item.category === 'event') return item.calendarType === 'earnings' ? cards.earnings : cards.macro;
  return item.category === 'news' ? cards.news : cards.analysis;
}

let requestId = 0;
async function load(append = false) {
  if (append && (loading.value || !hasMore.value || !nextCursor.value)) return;
  const cursor = append ? nextCursor.value! : undefined;
  if (!append) {
    items.value = [];
    nextCursor.value = null;
    hasMore.value = false;
  }
  const id = ++requestId;
  loading.value = true;
  error.value = null;
  try {
    const response = await timelineApi.list({ ...query.value, cursor, limit: 20 });
    if (id !== requestId) return;
    items.value = append ? [...items.value, ...response.items] : response.items;
    total.value = response.total;
    nextCursor.value = response.nextCursor;
    hasMore.value = response.hasMore;
  } catch (err) { if (id === requestId) error.value = getParsedApiError(err); }
  finally { if (id === requestId) loading.value = false; }
}
watch([query, displayTimezone], () => { void load(); }, { immediate: true });

const newsFields = [
  ['importanceScore', '重要性评分'], ['importanceReason', '重要性依据'], ['eventType', '事件类型'],
  ['timeSensitivity', '时效性'], ['importanceConfidence', '重要性置信度'], ['impact', '影响方向'],
  ['impactScore', '影响评分'], ['impactReason', '影响依据'], ['impactConfidence', '影响置信度'],
  ['watchPoints', '观察要点'], ['riskNotes', '风险提示'],
] as const;
function fieldText(value: unknown) { return Array.isArray(value) ? value.join('\n') : String(value ?? '—'); }
function safeUrl(value: unknown) { return typeof value === 'string' && /^https?:\/\//i.test(value) ? value : undefined; }
</script>

<template>
  <div
    class="w-full py-6"
    data-testid="investment-timeline"
  >
    <header class="overflow-hidden rounded-xl border border-border bg-gradient-to-br from-primary/8 via-card to-card p-5 shadow-sm sm:p-6">
      <p class="text-xs tracking-[0.2em] text-muted-foreground">
        INVESTMENT TIMELINE
      </p>
      <h1 class="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">
        投资时间线
      </h1>
      <p class="mt-2 max-w-3xl text-sm text-muted-foreground">
        公共市场信息看板：财报、宏观、新闻与市场分析统一按事件时间从新到旧排列，未来事件同样排在最前。
      </p>
    </header>

    <div class="mt-4 space-y-3 rounded-xl border border-border bg-card p-3 shadow-sm sm:p-4">
      <div
        class="flex flex-wrap items-center gap-2"
        aria-label="市场筛选"
      >
        <button
          v-for="option in markets"
          :key="option.value"
          type="button"
          class="h-10 rounded-lg border px-3.5 text-sm transition-colors duration-150"
          :class="market === option.value
            ? 'border-transparent bg-foreground text-background font-medium'
            : 'border-border text-muted-foreground hover:bg-muted'"
          :aria-pressed="market === option.value"
          @click="market = option.value"
        >
          {{ option.label }}
        </button>
        <select
          v-model="importance"
          aria-label="重要性"
          class="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm sm:ml-auto sm:w-40"
        >
          <option value="">
            全部重要性
          </option>
          <option
            v-for="value in (['critical', 'high', 'normal', 'low'] as const)"
            :key="value"
            :value="value"
          >
            {{ importanceNames[value] }}
          </option>
        </select>
      </div>
      <div
        class="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1"
        aria-label="内容类型筛选"
      >
        <button
          v-for="option in tabs"
          :key="option.value"
          type="button"
          class="h-9 shrink-0 whitespace-nowrap rounded-lg px-3.5 text-sm transition-colors duration-150"
          :class="tab === option.value
            ? 'bg-primary/10 font-semibold text-primary'
            : 'text-muted-foreground hover:bg-muted'"
          :aria-pressed="tab === option.value"
          @click="tab = option.value"
        >
          {{ option.label }}
        </button>
        <span class="ml-auto shrink-0 self-center pl-3 text-xs text-muted-foreground block">
          {{ displayTimezone === 'Asia/Shanghai' ? '北京时间' : '美东时间' }}
        </span>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <div
          class="flex max-w-full gap-1 overflow-x-auto"
          aria-label="截止日期快捷筛选"
        >
          <button
            v-for="option in presets"
            :key="option.value"
            type="button"
            class="h-10 shrink-0 whitespace-nowrap rounded-lg px-3 text-sm transition-colors"
            :class="preset === option.value ? 'bg-primary/10 font-semibold text-primary' : 'text-muted-foreground hover:bg-muted'"
            :aria-label="option.label"
            :aria-pressed="preset === option.value"
            @click="selectPreset(option.value)"
          >
            {{ option.label }}
          </button>
        </div>
        <AppDatePicker
          :model-value="endDate"
          :clearable="false"
          class="w-full sm:w-56"
          placeholder="截止日期"
          @update:model-value="selectCustomDate"
        />
      </div>
    </div>

    <ApiErrorAlert
      v-if="error"
      :error="error"
      class="mt-4"
    />
    <div
      v-if="loading && !items.length"
      class="mt-4 columns-3 gap-3 2xl:columns-4"
      aria-label="正在加载"
    >
      <div class="mb-3 h-36 break-inside-avoid animate-pulse rounded-xl bg-muted" />
      <div class="mb-3 h-52 break-inside-avoid animate-pulse rounded-xl bg-muted" />
      <div class="mb-3 h-28 break-inside-avoid animate-pulse rounded-xl bg-muted" />
      <div class="mb-3 h-44 break-inside-avoid animate-pulse rounded-xl bg-muted" />
      <div class="mb-3 h-32 break-inside-avoid animate-pulse rounded-xl bg-muted" />
      <div class="mb-3 h-48 break-inside-avoid animate-pulse rounded-xl bg-muted" />
    </div>
    <div
      v-else-if="!items.length && !error"
      class="mt-4 rounded-xl border border-dashed border-border px-6 py-16 text-center"
    >
      <p class="font-medium">
        暂无匹配的信息
      </p>
      <p class="mt-2 text-sm text-muted-foreground">
        试试调整市场、类型或截止日期。
      </p>
    </div>

    <div class="mt-4 space-y-6">
      <section
        v-for="group in groups"
        :key="group.key"
        class="space-y-2.5"
      >
        <h2 class="sticky top-14 z-10 -mx-1 bg-background/90 px-1 py-1.5 text-xs font-medium tabular-nums text-muted-foreground backdrop-blur">
          {{ dayHeading(group.key) }}
        </h2>
        <div
          class="columns-3 gap-3 2xl:columns-4"
          data-testid="timeline-columns"
        >
          <div
            v-for="item in group.items"
            :key="item.id"
            class="mb-3 break-inside-avoid"
          >
            <component
              :is="cardFor(item)"
              :item="item"
              @open="detail = item"
            />
          </div>
        </div>
      </section>
    </div>

    <div
      v-if="hasMore"
      class="mt-6 text-center"
    >
      <LoadingButton
        variant="outline"
        :loading="loading"
        @click="load(true)"
      >
        加载更多
      </LoadingButton>
    </div>
    <p
      v-else-if="items.length"
      class="mt-6 text-center text-xs text-muted-foreground"
    >
      已显示全部 {{ total }} 条信息
    </p>

    <Dialog
      :open="!!detail"
      @update:open="value => { if (!value) detail = null; }"
    >
      <DialogScrollContent class="sm:max-w-3xl">
        <template v-if="detail">
          <DialogHeader>
            <DialogTitle>{{ detail.title }}</DialogTitle>
            <DialogDescription>
              {{ kindLabel(detail) }}{{ detail.market ? ` · ${marketLabel(detail.market)}` : '' }} ·
              {{ formatDateTimeInDisplayTimezone(detail.eventTime) }} · {{ importanceNames[detail.importance] }}
            </DialogDescription>
          </DialogHeader>
          <TimelineEventDetail
            v-if="detail.category === 'event'"
            :item="detail"
          />
          <template v-else-if="detail.category === 'news'">
            <p
              v-if="detail.relatedSymbols.length"
              class="text-sm font-medium"
            >
              {{ detail.relatedSymbols.join(' · ') }}
            </p>
            <p class="text-sm text-muted-foreground">
              {{ detail.detailPayload.source }} ·
              {{ detail.detailPayload.publishedAt ? formatDateTimeInDisplayTimezone(String(detail.detailPayload.publishedAt)) : '发布时间未提供' }}
            </p>
            <a
              v-if="safeUrl(detail.detailPayload.url)"
              :href="safeUrl(detail.detailPayload.url)"
              target="_blank"
              rel="noopener noreferrer"
              class="text-sm underline"
            >阅读原文 ↗</a>
            <dl class="space-y-4">
              <div
                v-for="[key, label] in newsFields"
                :key="key"
              >
                <dt class="text-xs text-muted-foreground">
                  {{ label }}
                </dt>
                <dd class="mt-1 whitespace-pre-line text-sm leading-relaxed">
                  {{ fieldText(detail.detailPayload[key]) }}
                </dd>
              </div>
            </dl>
          </template>
          <div
            v-else
            class="prose prose-sm max-w-none break-words dark:prose-invert"
            v-html="renderMarkdownToHtml(String(detail.detailPayload.content || ''))"
          />
        </template>
      </DialogScrollContent>
    </Dialog>
  </div>
</template>
