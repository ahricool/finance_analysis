<script setup lang="ts">
import {
  calendarApi,
  type CalendarEntryCategory,
  type CalendarEntryItem,
  type CalendarSummaryItem,
  type FinanceEventItem,
} from '@/api/calendar';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Button from '@/components/common/Button.vue';
import Dialog from '@/components/common/Dialog.vue';
import Input from '@/components/common/Input.vue';
import Pagination from '@/components/common/Pagination.vue';
import CollapsibleCalendarSection from '@/components/calendar/CollapsibleCalendarSection.vue';
import { useTimezoneStore } from '@/stores/timezoneStore';
import {
  formatDateOnly,
  formatDateTimeInDisplayTimezone,
  getTodayInDisplayTimezone,
  localDateTimeToUtcIso,
} from '@/utils/format';
import { renderMarkdownToHtml } from '@/utils/renderMarkdown';
import { CalendarDays, ChevronLeft, ChevronRight, FileSearch, Plus } from 'lucide-vue-next';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';

const WEEKDAY_CN = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'] as const;
const PAGE_SIZE = 20;

interface EntrySectionState {
  items: CalendarEntryItem[];
  total: number;
  page: number;
  loading: boolean;
  open: boolean;
}

const entrySectionDefinitions: ReadonlyArray<{
  category: CalendarEntryCategory;
  title: string;
  description: string;
}> = [
  { category: 'a_share', title: 'A股日历', description: 'A股盘中分析、异动信号和信号评价' },
  { category: 'us', title: '美股日历', description: '美股盘前、盘中信号、收盘复盘和信号评价' },
  { category: 'news', title: '新闻日历', description: '盘前新闻抓取、筛选和影响判断' },
  { category: 'other', title: '其他日历', description: '每日全量、财经同步、手动记录及未分类记录' },
];

const timezoneStore = useTimezoneStore();
const { displayTimezone } = storeToRefs(timezoneStore);
const initialSelectedDate = getTodayInDisplayTimezone();
const todayInDisplayTimezone = ref(initialSelectedDate);
const dateRangeStart = ref(addDays(parseDateOnly(initialSelectedDate), -1));
const selectedDate = ref(initialSelectedDate);
const events = ref<FinanceEventItem[]>([]);
const eventsTotal = ref(0);
const eventsPage = ref(1);
const eventsOpen = ref(true);
const summaryByDate = ref<Record<string, CalendarSummaryItem>>({});
const eventsLoading = ref(false);
const entrySections = reactive<Record<CalendarEntryCategory, EntrySectionState>>({
  a_share: { items: [], total: 0, page: 1, loading: false, open: false },
  us: { items: [], total: 0, page: 1, loading: false, open: true },
  news: { items: [], total: 0, page: 1, loading: false, open: false },
  other: { items: [], total: 0, page: 1, loading: false, open: false },
});
const summaryLoading = ref(false);
const error = ref<ParsedApiError | null>(null);
const createMode = ref<'event' | 'entry' | null>(null);
const createSaving = ref(false);
const createError = ref<ParsedApiError | null>(null);
const eventForm = reactive({
  eventDate: initialSelectedDate,
  eventTime: '',
  calendarType: 'macro',
  market: 'US',
  symbol: '',
  counterName: '',
  title: '',
  content: '',
  star: '',
  currency: '',
});
const entryForm = reactive({
  time: `${initialSelectedDate}T09:00`,
  title: '',
  type: '',
  content: '',
});

type CalendarDetail =
  | { kind: 'event'; item: FinanceEventItem }
  | { kind: 'entry'; item: CalendarEntryItem };

const detail = ref<CalendarDetail | null>(null);

const detailTitle = computed(() => {
  if (!detail.value) return '';
  return detail.value.kind === 'event' ? '财经事件详情' : '日历记录详情';
});
const createTitle = computed(() => (createMode.value === 'event' ? '新增财经事件' : '新增日历记录'));

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

function totalPages(total: number): number {
  return Math.max(1, Math.ceil(total / PAGE_SIZE));
}

async function loadFinanceEventsPage(page: number) {
  const date = selectedDate.value;
  eventsLoading.value = true;
  try {
    const response = await calendarApi.listEventsByDate(date, page, PAGE_SIZE);
    if (date !== selectedDate.value) return;
    events.value = response.items;
    eventsTotal.value = response.total;
    eventsPage.value = response.page;
  } catch (e) {
    error.value = getParsedApiError(e);
  } finally {
    eventsLoading.value = false;
  }
}

async function loadEntrySectionPage(category: CalendarEntryCategory, page: number) {
  const date = selectedDate.value;
  const section = entrySections[category];
  section.loading = true;
  try {
    const response = await calendarApi.listByDate(date, { category, page, limit: PAGE_SIZE });
    if (date !== selectedDate.value) return;
    section.items = response.items;
    section.total = response.total;
    section.page = response.page;
  } catch (e) {
    error.value = getParsedApiError(e);
  } finally {
    section.loading = false;
  }
}

async function loadSelectedDateDetails() {
  error.value = null;
  detail.value = null;
  eventsPage.value = 1;
  for (const definition of entrySectionDefinitions) {
    entrySections[definition.category].page = 1;
  }
  await Promise.all([
    loadFinanceEventsPage(1),
    ...entrySectionDefinitions.map(({ category }) => loadEntrySectionPage(category, 1)),
  ]);
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

function goToDate(date: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
  selectedDate.value = date;
  dateRangeStart.value = addDays(parseDateOnly(date), -1);
  detail.value = null;
  void Promise.all([loadSelectedDateDetails(), loadRangeSummary()]);
}

function selectDisplayDate(event: Event) {
  goToDate((event.target as HTMLInputElement).value);
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

function openCreate(mode: 'event' | 'entry') {
  createMode.value = mode;
  createError.value = null;
  if (mode === 'event') {
    Object.assign(eventForm, {
      eventDate: selectedDate.value,
      eventTime: '',
      calendarType: 'macro',
      market: 'US',
      symbol: '',
      counterName: '',
      title: '',
      content: '',
      star: '',
      currency: '',
    });
  } else {
    Object.assign(entryForm, {
      time: `${selectedDate.value}T09:00`,
      title: '',
      type: '',
      content: '',
    });
  }
}

function closeCreate() {
  if (createSaving.value) return;
  createMode.value = null;
  createError.value = null;
}

function optionalText(value: string): string | null {
  return value.trim() || null;
}

async function submitCreate() {
  if (!createMode.value) return;
  createSaving.value = true;
  createError.value = null;
  try {
    let createdDate: string;
    if (createMode.value === 'event') {
      await calendarApi.createEvent({
        calendar_type: eventForm.calendarType,
        market: eventForm.market.trim(),
        symbol: optionalText(eventForm.symbol),
        counter_name: optionalText(eventForm.counterName),
        event_date: eventForm.eventDate,
        event_datetime: eventForm.eventTime
          ? localDateTimeToUtcIso(eventForm.eventTime, displayTimezone.value)
          : null,
        title: eventForm.title.trim(),
        content: eventForm.content.trim(),
        star: eventForm.star ? Number(eventForm.star) : null,
        currency: optionalText(eventForm.currency),
      });
      createdDate = eventForm.eventDate;
    } else {
      await calendarApi.createEntry({
        time: localDateTimeToUtcIso(entryForm.time, displayTimezone.value),
        title: entryForm.title.trim(),
        content: optionalText(entryForm.content),
        type: optionalText(entryForm.type),
      });
      createdDate = entryForm.time.slice(0, 10);
    }
    createMode.value = null;
    goToDate(createdDate);
  } catch (e) {
    createError.value = getParsedApiError(e);
  } finally {
    createSaving.value = false;
  }
}

function entryTypeLabel(type: string | null): string {
  if (type === 'scheduled_daily') return '定时全量';
  if (type === 'scheduled_market_calendar') return '财经日历同步';
  if (type === 'scheduled_a_share_intraday') return 'A股盘中分析';
  if (type === 'a_share_intraday_signal') return 'A股盘中信号';
  if (type === 'scheduled_signal_evaluation_cn') return 'A股信号评价';
  if (type === 'scheduled_us_premarket') return '美股盘前';
  if (type === 'scheduled_us_intraday') return '美股盘中分析';
  if (type === 'us_intraday_signal') return '美股盘中信号';
  if (type === 'scheduled_us_postmarket_review') return '美股收盘复盘';
  if (type === 'scheduled_signal_evaluation_us') return '美股信号评价';
  if (type === 'scheduled_us_premarket_news') return '盘前新闻';
  if (type === 'manual_note') return '手动记录';
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
    <div class="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-3">
        <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary-gradient text-[hsl(var(--primary-foreground))] shadow-soft-card">
          <CalendarDays class="h-5 w-5" />
        </div>
        <div>
          <h1 class="text-lg font-semibold text-foreground">日历记录</h1>
          <p class="text-xs text-secondary-text">按 7 日视图查看财经事件与自动化任务记录</p>
        </div>
      </div>
      <label class="flex items-center gap-2 text-xs font-medium text-secondary-text">
        展示日期
        <input
          :value="selectedDate"
          type="date"
          aria-label="展示日期"
          class="h-9 rounded-xl border border-border/70 bg-background px-3 text-sm text-foreground outline-none transition-colors focus:border-primary"
          @change="selectDisplayDate"
        />
      </label>
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

    <div class="space-y-3">
      <CollapsibleCalendarSection
        title="财经事件"
        :description="`${selectedDateDisplay} 的财报、宏观、分红、拆股和 IPO 事件`"
        :count="eventsTotal"
        :loading="eventsLoading"
        :open="eventsOpen"
        test-id="finance-events-section"
        @update:open="eventsOpen = $event"
      >
        <template #actions>
          <Button size="xsm" variant="secondary" data-testid="add-finance-event" @click="openCreate('event')">
            <Plus class="h-3.5 w-3.5" />
            新增事件
          </Button>
        </template>

        <div v-if="eventsLoading" class="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <div v-for="n in 3" :key="n" class="h-16 animate-pulse rounded-xl bg-hover" />
        </div>
        <div v-else-if="!events.length" class="py-6 text-sm text-secondary-text">当天暂无财经事件</div>
        <template v-else>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
              <FileSearch class="mt-0.5 h-4 w-4 shrink-0 text-secondary-text" />
            </button>
          </div>
          <Pagination
            :current-page="eventsPage"
            :total-pages="totalPages(eventsTotal)"
            class="pt-4"
            @page-change="loadFinanceEventsPage"
          />
        </template>
      </CollapsibleCalendarSection>

      <CollapsibleCalendarSection
        v-for="definition in entrySectionDefinitions"
        :key="definition.category"
        :title="definition.title"
        :description="`${selectedDateDisplay} · ${definition.description}`"
        :count="entrySections[definition.category].total"
        :loading="entrySections[definition.category].loading"
        :open="entrySections[definition.category].open"
        :test-id="`${definition.category}-calendar-section`"
        @update:open="entrySections[definition.category].open = $event"
      >
        <template #actions>
          <Button
            v-if="definition.category === 'other'"
            size="xsm"
            variant="secondary"
            data-testid="add-calendar-entry"
            @click="openCreate('entry')"
          >
            <Plus class="h-3.5 w-3.5" />
            新增记录
          </Button>
        </template>

        <div v-if="entrySections[definition.category].loading" class="space-y-2">
          <div v-for="n in 3" :key="n" class="h-12 animate-pulse rounded-xl bg-hover" />
        </div>
        <div
          v-else-if="!entrySections[definition.category].items.length"
          class="py-6 text-sm text-secondary-text"
        >
          当天暂无{{ definition.title }}记录
        </div>
        <template v-else>
          <div class="space-y-3">
            <button
              v-for="item in entrySections[definition.category].items"
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
              <FileSearch class="mt-0.5 h-4 w-4 shrink-0 text-secondary-text" />
            </button>
          </div>
          <Pagination
            :current-page="entrySections[definition.category].page"
            :total-pages="totalPages(entrySections[definition.category].total)"
            class="pt-4"
            @page-change="loadEntrySectionPage(definition.category, $event)"
          />
        </template>
      </CollapsibleCalendarSection>
    </div>

    <Dialog
      :is-open="!!createMode"
      :title="createTitle"
      width="max-w-2xl"
      @close="closeCreate"
    >
      <form class="space-y-4" data-testid="calendar-create-form" @submit.prevent="submitCreate">
        <ApiErrorAlert v-if="createError" :error="createError" />

        <template v-if="createMode === 'event'">
          <div class="grid gap-4 sm:grid-cols-2">
            <Input v-model="eventForm.eventDate" label="事件日期 *" type="date" required />
            <Input
              v-model="eventForm.eventTime"
              label="具体时间（可选）"
              type="datetime-local"
              :hint="`按 ${displayTimezone} 录入`"
            />
            <Input
              v-model="eventForm.calendarType"
              label="事件类型 *"
              list="calendar-event-types"
              maxlength="32"
              placeholder="例如 macro"
              required
            />
            <datalist id="calendar-event-types">
              <option value="macro">宏观</option>
              <option value="earnings">财报</option>
              <option value="dividend">分红</option>
              <option value="split">拆股</option>
              <option value="ipo">IPO</option>
            </datalist>
            <Input v-model="eventForm.market" label="市场 *" maxlength="16" required />
            <Input v-model="eventForm.symbol" label="股票代码" maxlength="32" placeholder="例如 AAPL" />
            <Input v-model="eventForm.counterName" label="标的名称" maxlength="128" />
            <Input v-model="eventForm.currency" label="币种" maxlength="16" placeholder="例如 USD" />
            <Input v-model="eventForm.star" label="星级（0-5）" type="number" min="0" max="5" />
          </div>
          <Input v-model="eventForm.title" label="标题 *" maxlength="120" required />
          <div>
            <label class="mb-2 block text-sm font-medium text-foreground" for="event-content">详情内容</label>
            <textarea
              id="event-content"
              v-model="eventForm.content"
              class="input-surface input-focus-glow min-h-32 w-full rounded-xl border bg-transparent px-4 py-3 text-sm text-foreground focus:outline-none"
              placeholder="支持 Markdown"
            />
          </div>
        </template>

        <template v-else-if="createMode === 'entry'">
          <Input
            v-model="entryForm.time"
            label="记录时间 *"
            type="datetime-local"
            :hint="`按 ${displayTimezone} 录入`"
            required
          />
          <Input v-model="entryForm.title" label="标题 *" maxlength="120" required />
          <Input v-model="entryForm.type" label="记录类型" maxlength="32" placeholder="例如 manual_note" />
          <div>
            <label class="mb-2 block text-sm font-medium text-foreground" for="entry-content">详情内容</label>
            <textarea
              id="entry-content"
              v-model="entryForm.content"
              class="input-surface input-focus-glow min-h-32 w-full rounded-xl border bg-transparent px-4 py-3 text-sm text-foreground focus:outline-none"
              placeholder="支持 Markdown"
            />
          </div>
        </template>

        <div class="flex justify-end gap-2 pt-2">
          <Button variant="ghost" :disabled="createSaving" @click="closeCreate">取消</Button>
          <Button type="submit" :is-loading="createSaving" loading-text="保存中…">保存</Button>
        </div>
      </form>
    </Dialog>

    <Dialog
      :is-open="!!detail"
      :title="detailTitle"
      width="max-w-4xl"
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
    </Dialog>
  </div>
</template>
