<script setup lang="ts">
import { calendarApi, type CalendarEntryItem, type CalendarSummaryItem, type FinanceEventItem } from '@/api/calendar';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Drawer from '@/components/common/Drawer.vue';
import { useTimezoneStore } from '@/stores/timezoneStore';
import { formatDateOnly, formatDateTimeInDisplayTimezone, getTodayInDisplayTimezone } from '@/utils/format';
import { renderMarkdownToHtml } from '@/utils/renderMarkdown';
import { CalendarDays, ChevronLeft, ChevronRight, FileSearch } from 'lucide-vue-next';
import { computed, onMounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';

const WEEKDAY_CN = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'] as const;

const timezoneStore = useTimezoneStore();
const { displayTimezone } = storeToRefs(timezoneStore);
const initialSelectedDate = getTodayInDisplayTimezone();
const todayInDisplayTimezone = ref(initialSelectedDate);
const dateRangeStart = ref(addDays(parseDateOnly(initialSelectedDate), -1));
const selectedDate = ref(initialSelectedDate);
const events = ref<FinanceEventItem[]>([]);
const entries = ref<CalendarEntryItem[]>([]);
const summaryByDate = ref<Record<string, CalendarSummaryItem>>({});
const eventsLoading = ref(false);
const entriesLoading = ref(false);
const summaryLoading = ref(false);
const error = ref<ParsedApiError | null>(null);

type CalendarDetail =
  | { kind: 'event'; item: FinanceEventItem }
  | { kind: 'entry'; item: CalendarEntryItem };

const detail = ref<CalendarDetail | null>(null);

const detailTitle = computed(() => {
  if (!detail.value) return '';
  return detail.value.kind === 'event' ? '财经事件详情' : '日历记录详情';
});

const rangeDates = computed(() => Array.from({ length: 7 }, (_, i) => addDays(dateRangeStart.value, i)));
const rangeEnd = computed(() => addDays(dateRangeStart.value, 6));
const rangeDisplay = computed(() => `${formatMonthDay(dateRangeStart.value)} - ${formatMonthDay(rangeEnd.value)}`);
const isDefaultTodayView = computed(
  () =>
    formatDate(dateRangeStart.value) === defaultRangeStart(todayInDisplayTimezone.value) &&
    selectedDate.value === todayInDisplayTimezone.value,
);

function addDays(d: Date, n: number): Date {
  const copy = new Date(d);
  copy.setUTCDate(copy.getUTCDate() + n);
  return copy;
}
function formatDate(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function formatMonthDay(d: Date): string {
  return `${String(d.getUTCMonth() + 1).padStart(2, '0')}/${String(d.getUTCDate()).padStart(2, '0')}`;
}

function parseDateOnly(value: string): Date {
  const [y, m, d] = value.split('-').map(Number);
  return new Date(Date.UTC(y, (m || 1) - 1, d || 1));
}

function weekdayCn(d: Date): string {
  return WEEKDAY_CN[d.getUTCDay()] ?? '';
}

/** 展示用：YYYY-MM-DD 星期x */
function dateWithWeekday(d: Date): string {
  return `${formatDate(d)} ${weekdayCn(d)}`;
}

function defaultRangeStart(today: string): string {
  return formatDate(addDays(parseDateOnly(today), -1));
}

const selectedDateDisplay = computed(() => {
  const parts = selectedDate.value.split('-').map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return selectedDate.value;
  return dateWithWeekday(parseDateOnly(selectedDate.value));
});

async function loadSelectedDateDetails() {
  eventsLoading.value = true;
  entriesLoading.value = true;
  error.value = null;
  detail.value = null;
  const date = selectedDate.value;
  try {
    const [eventRes, entryRes] = await Promise.all([
      calendarApi.listEventsByDate(date),
      calendarApi.listByDate(date),
    ]);
    events.value = eventRes.items;
    entries.value = entryRes.items;
  } catch (e) {
    error.value = getParsedApiError(e);
  } finally {
    eventsLoading.value = false;
    entriesLoading.value = false;
  }
}

async function loadRangeSummary() {
  summaryLoading.value = true;
  error.value = null;
  try {
    const result = await calendarApi.getSummary(formatDate(dateRangeStart.value), formatDate(rangeEnd.value));
    summaryByDate.value = Object.fromEntries(result.items.map((item) => [item.date, item]));
  } catch (e) {
    error.value = getParsedApiError(e);
  } finally {
    summaryLoading.value = false;
  }
}

function selectDate(d: Date) {
  const nextDate = formatDate(d);
  if (nextDate === selectedDate.value) return;
  selectedDate.value = nextDate;
  void loadSelectedDateDetails();
}

function shiftRange(step: number) {
  const currentIndex = rangeDates.value.findIndex((d) => formatDate(d) === selectedDate.value);
  const selectedIndex = currentIndex >= 0 ? currentIndex : 1;
  const nextStart = addDays(dateRangeStart.value, step * 7);
  dateRangeStart.value = nextStart;
  selectedDate.value = formatDate(addDays(nextStart, selectedIndex));
  detail.value = null;
  void Promise.all([loadSelectedDateDetails(), loadRangeSummary()]);
}

function goToday() {
  const today = getTodayInDisplayTimezone();
  todayInDisplayTimezone.value = today;
  dateRangeStart.value = parseDateOnly(defaultRangeStart(today));
  selectedDate.value = today;
  detail.value = null;
  void Promise.all([loadSelectedDateDetails(), loadRangeSummary()]);
}

function dateSummary(d: Date): CalendarSummaryItem {
  const date = formatDate(d);
  return summaryByDate.value[date] ?? { date, finance_event_count: 0, calendar_entry_count: 0 };
}

function countToneClass(count: number): string {
  if (count <= 0) return 'text-muted-text';
  if (count <= 2) return 'text-primary';
  if (count <= 5) return 'text-warning';
  return 'text-danger';
}

function countTone(count: number): string {
  if (count <= 0) return 'muted';
  if (count <= 2) return 'primary';
  if (count <= 5) return 'warning';
  return 'danger';
}

function dateButtonClass(d: Date) {
  const date = formatDate(d);
  const selected = selectedDate.value === date;
  const today = todayInDisplayTimezone.value === date;
  if (selected) return 'border-primary bg-primary/10 text-primary shadow-[0_0_0_1px_hsl(var(--primary)/0.18)]';
  if (today) return 'border-primary/35 bg-primary/5 hover:bg-primary/10';
  return 'border-border/60 hover:bg-hover';
}

function openEventDetail(item: FinanceEventItem) {
  detail.value = { kind: 'event', item };
}

function openEntryDetail(item: CalendarEntryItem) {
  detail.value = { kind: 'entry', item };
}

function closeDetail() {
  detail.value = null;
}

function entryTypeLabel(type: string | null): string {
  if (type === 'scheduled_daily') return '定时全量';
  if (type === 'scheduled_market_calendar') return '财经日历';
  if (type === 'scheduled_us_premarket') return '美股盘前';
  if (type === 'scheduled_us_premarket_news') return '盘前新闻';
  return type || '日历记录';
}

function eventTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    earnings: '财报',
    dividend: '分红',
    split: '拆股',
    ipo: 'IPO',
    macro: '宏观',
  };
  return labels[type] ?? type;
}

function eventName(item: FinanceEventItem): string {
  return [item.symbol, item.counter_name].filter(Boolean).join(' / ') || item.market;
}

function eventTime(item: FinanceEventItem): string {
  if (item.event_datetime) return formatDateTimeInDisplayTimezone(item.event_datetime);
  return item.financial_market_time || formatDateOnly(item.event_date);
}

function importanceLabel(item: FinanceEventItem): string {
  return item.importance_score !== null ? `${item.importance_score}/10` : '待评估';
}

function isHighImportance(item: FinanceEventItem): boolean {
  return (item.importance_score ?? 0) >= 8;
}

function renderMarkdown(content: string | null): string {
  if (!content) return '';
  return renderMarkdownToHtml(content);
}

onMounted(() => {
  void Promise.all([loadSelectedDateDetails(), loadRangeSummary()]);
});

watch(displayTimezone, () => {
  const nextToday = getTodayInDisplayTimezone();
  todayInDisplayTimezone.value = nextToday;
  dateRangeStart.value = parseDateOnly(defaultRangeStart(nextToday));
  selectedDate.value = nextToday;
  detail.value = null;
  void Promise.all([loadSelectedDateDetails(), loadRangeSummary()]);
});
</script>

<template>
  <div class="mx-auto w-full px-4 py-6 sm:px-6">
    <div class="mb-6 flex items-center gap-3">
      <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary-gradient text-[hsl(var(--primary-foreground))] shadow-soft-card">
        <CalendarDays class="h-5 w-5" />
      </div>
      <div>
        <h1 class="text-lg font-semibold text-foreground">日历记录</h1>
        <p class="text-xs text-secondary-text">按 7 日视图查看财经事件与自动化任务记录</p>
      </div>
    </div>

    <div class="mb-4 rounded-2xl border border-border/60 bg-card p-4">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          class="rounded-lg p-2 text-secondary-text transition-colors hover:bg-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          aria-label="上一周期"
          :disabled="summaryLoading"
          @click="shiftRange(-1)"
        >
          <ChevronLeft class="h-4 w-4" />
        </button>
        <p class="text-center text-sm font-medium">
          <span>7 日视图</span>
          <span class="mx-2 text-secondary-text">/</span>
          <span class="font-mono text-secondary-text">{{ rangeDisplay }}</span>
        </p>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="rounded-lg border border-border/70 px-3 py-1.5 text-xs font-medium text-secondary-text transition-colors hover:bg-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="isDefaultTodayView"
            @click="goToday"
          >
            今天
          </button>
          <button
            type="button"
            class="rounded-lg p-2 text-secondary-text transition-colors hover:bg-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="下一周期"
            :disabled="summaryLoading"
            @click="shiftRange(1)"
          >
            <ChevronRight class="h-4 w-4" />
          </button>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-1.5 min-[430px]:grid-cols-4 sm:grid-cols-7 sm:gap-2">
        <button
          v-for="d in rangeDates"
          :key="formatDate(d)"
          type="button"
          class="relative flex min-h-24 flex-col items-center justify-center gap-1.5 rounded-xl border px-2 py-2 text-center leading-tight transition-colors disabled:cursor-not-allowed disabled:opacity-60 sm:min-h-28"
          :class="[dateButtonClass(d), summaryLoading ? 'animate-pulse' : '']"
          :disabled="summaryLoading"
          :aria-label="dateWithWeekday(d)"
          data-testid="calendar-day"
          @click="selectDate(d)"
        >
          <span class="block whitespace-nowrap text-sm font-semibold">{{ formatMonthDay(d) }}</span>
          <span
            class="block whitespace-nowrap text-[11px] text-secondary-text"
            :class="selectedDate === formatDate(d) ? 'text-primary' : ''"
          >
            {{ weekdayCn(d) }}
          </span>
          <span class="mt-1 flex w-full flex-col items-center gap-0.5 text-[11px] text-secondary-text min-[520px]:flex-row min-[520px]:justify-center min-[520px]:gap-2">
            <span class="whitespace-nowrap">
              财经
              <span
                class="font-semibold tabular-nums"
                :class="countToneClass(dateSummary(d).finance_event_count)"
                :data-count-tone="countTone(dateSummary(d).finance_event_count)"
              >
                {{ dateSummary(d).finance_event_count }}
              </span>
            </span>
            <span class="whitespace-nowrap">
              记录
              <span
                class="font-semibold tabular-nums"
                :class="countToneClass(dateSummary(d).calendar_entry_count)"
                :data-count-tone="countTone(dateSummary(d).calendar_entry_count)"
              >
                {{ dateSummary(d).calendar_entry_count }}
              </span>
            </span>
          </span>
          <span
            v-if="todayInDisplayTimezone === formatDate(d) && selectedDate !== formatDate(d)"
            class="absolute bottom-1.5 h-1.5 w-1.5 rounded-full bg-primary/70"
            aria-hidden="true"
          />
        </button>
      </div>
    </div>

    <ApiErrorAlert v-if="error" :error="error" class="mb-4" />

    <div class="mb-4 rounded-2xl border border-border/60 bg-card p-4">
      <h2 class="mb-3 text-xs font-semibold sm:text-sm">{{ selectedDateDisplay }} 财经事件</h2>
      <div v-if="eventsLoading" class="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <div v-for="n in 3" :key="n" class="h-16 animate-pulse rounded-xl bg-hover" />
      </div>
      <div v-else-if="!events.length" class="py-6 text-sm text-secondary-text">当天暂无财经事件</div>
      <div v-else class="max-h-[320px] overflow-y-auto">
        <div class="grid grid-cols-1 gap-3 p-2 sm:grid-cols-2 lg:grid-cols-3">
          <button
            v-for="item in events"
            :key="item.id"
            type="button"
            class="terminal-card terminal-card-hover flex h-full w-full cursor-pointer items-start justify-between gap-3 p-3 text-left"
            :class="isHighImportance(item) ? 'border-warning/30' : ''"
            @click="openEventDetail(item)"
          >
            <span class="min-w-0 flex-1">
              <span class="mb-1 flex flex-wrap items-center gap-2 text-xs text-secondary-text">
                <span class="rounded-full bg-hover px-2 py-0.5">{{ eventTypeLabel(item.calendar_type) }}</span>
                <span>{{ eventName(item) }}</span>
                <span
                  class="rounded-full px-2 py-0.5"
                  :class="isHighImportance(item) ? 'bg-warning/10 text-warning' : 'bg-hover text-secondary-text'"
                >
                  {{ importanceLabel(item) }}
                </span>
                <span v-if="item.star !== null">star {{ item.star }}</span>
                <span>{{ eventTime(item) }}</span>
              </span>
              <span class="block text-sm font-medium">{{ item.title }}</span>
              <span class="mt-1 block text-xs text-secondary-text">{{ formatDateOnly(item.event_date) }}</span>
            </span>
            <span class="mt-0.5 inline-flex shrink-0 items-center gap-1 text-xs text-secondary-text">
              <FileSearch class="h-4 w-4" />
            </span>
          </button>
        </div>
      </div>
    </div>

    <div class="rounded-2xl border border-border/60 bg-card p-4">
      <h2 class="mb-3 text-xs font-semibold sm:text-sm">{{ selectedDateDisplay }} 日历记录</h2>
      <div v-if="entriesLoading" class="space-y-2"><div v-for="n in 3" :key="n" class="h-12 animate-pulse rounded-xl bg-hover" /></div>
      <div v-else-if="!entries.length" class="py-6 text-sm text-secondary-text">当天暂无日历记录</div>
      <div v-else class="space-y-3 p-2">
        <button
          v-for="item in entries"
          :key="item.id"
          type="button"
          class="terminal-card terminal-card-hover flex w-full cursor-pointer items-start justify-between gap-3 p-3 text-left"
          @click="openEntryDetail(item)"
        >
          <span class="min-w-0 flex-1">
            <span class="block text-sm font-medium">{{ item.title }}</span>
            <span class="mt-1 flex flex-wrap items-center gap-2 text-xs text-secondary-text">
              <span class="rounded-full bg-hover px-2 py-0.5">{{ entryTypeLabel(item.type) }}</span>
              <span>{{ formatDateTimeInDisplayTimezone(item.time) }}</span>
              <span v-if="item.content">点击查看执行结果与报告</span>
            </span>
          </span>
          <span class="mt-0.5 inline-flex shrink-0 items-center gap-1 text-xs text-secondary-text">
            <FileSearch class="h-4 w-4" />
          </span>
        </button>
      </div>
    </div>

    <Drawer
      :is-open="!!detail"
      :title="detailTitle"
      width="max-w-4xl"
      variant="modal"
      @close="closeDetail"
    >
      <div v-if="detail?.kind === 'event'" class="space-y-5">
        <div class="grid gap-3 sm:grid-cols-2">
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">类型</p>
            <p class="mt-1 text-sm font-medium text-foreground">{{ eventTypeLabel(detail.item.calendar_type) }}</p>
          </div>
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">标的 / 名称</p>
            <p class="mt-1 text-sm text-foreground">{{ eventName(detail.item) }}</p>
          </div>
          <div v-if="detail.item.star !== null" class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">Provider star</p>
            <p class="mt-1 text-sm text-foreground">{{ detail.item.star }}</p>
          </div>
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">重要性</p>
            <p class="mt-1 text-sm text-foreground">{{ importanceLabel(detail.item) }}</p>
          </div>
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">时间</p>
            <p class="mt-1 text-sm text-foreground">{{ eventTime(detail.item) }}</p>
          </div>
          <div v-if="detail.item.importance_reason" class="rounded-xl border border-border/60 bg-background/60 p-3 sm:col-span-2">
            <p class="text-xs text-muted-text">重要性原因</p>
            <p class="mt-1 text-sm text-foreground">{{ detail.item.importance_reason }}</p>
          </div>
          <div class="rounded-xl border border-border/60 bg-background/60 p-3 sm:col-span-2">
            <p class="text-xs text-muted-text">标题</p>
            <p class="mt-1 text-sm font-medium text-foreground">{{ detail.item.title }}</p>
          </div>
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">日期</p>
            <p class="mt-1 text-sm text-foreground">{{ formatDateOnly(detail.item.event_date) }}</p>
          </div>
        </div>

        <div class="rounded-xl border border-border/60 bg-background/60 p-3">
          <p class="text-xs text-muted-text">详情内容</p>
          <div
            v-if="detail.item.content"
            class="prose prose-sm mt-3 max-w-none text-sm text-foreground dark:prose-invert"
            v-html="renderMarkdown(detail.item.content)"
          />
          <p v-else class="mt-2 text-sm text-secondary-text">该事件暂无详情内容</p>
        </div>
      </div>

      <div v-else-if="detail?.kind === 'entry'" class="space-y-5">
        <div class="grid gap-3 sm:grid-cols-2">
          <div class="rounded-xl border border-border/60 bg-background/60 p-3 sm:col-span-2">
            <p class="text-xs text-muted-text">标题</p>
            <p class="mt-1 text-sm font-medium text-foreground">{{ detail.item.title }}</p>
          </div>
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">类型</p>
            <p class="mt-1 text-sm text-foreground">{{ entryTypeLabel(detail.item.type) }}</p>
          </div>
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">时间</p>
            <p class="mt-1 text-sm text-foreground">{{ formatDateTimeInDisplayTimezone(detail.item.time) }}</p>
          </div>
        </div>

        <div class="rounded-xl border border-border/60 bg-background/60 p-3">
          <p class="text-xs text-muted-text">详情内容</p>
          <div
            v-if="detail.item.content"
            class="prose prose-sm mt-3 max-w-none text-sm text-foreground dark:prose-invert"
            v-html="renderMarkdown(detail.item.content)"
          />
          <p v-else class="mt-2 text-sm text-secondary-text">该记录暂无详情内容</p>
        </div>
      </div>
    </Drawer>
  </div>
</template>
