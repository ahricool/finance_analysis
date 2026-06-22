<script setup lang="ts">
import { calendarApi, type CalendarEntryItem, type FinanceEventItem } from '@/api/calendar';
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
const weekStart = ref(startOfWeek(parseDateOnly(initialSelectedDate)));
const selectedDate = ref(initialSelectedDate);
const events = ref<FinanceEventItem[]>([]);
const entries = ref<CalendarEntryItem[]>([]);
const eventsLoading = ref(false);
const entriesLoading = ref(false);
const error = ref<ParsedApiError | null>(null);

type CalendarDetail =
  | { kind: 'event'; item: FinanceEventItem }
  | { kind: 'entry'; item: CalendarEntryItem };

const detail = ref<CalendarDetail | null>(null);

const detailTitle = computed(() => {
  if (!detail.value) return '';
  return detail.value.kind === 'event' ? '财经事件详情' : '日历记录详情';
});

const weekDates = computed(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart.value, i)));

function startOfWeek(d: Date): Date {
  const copy = new Date(d);
  const day = copy.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  copy.setDate(copy.getDate() + diff);
  copy.setHours(0, 0, 0, 0);
  return copy;
}
function addDays(d: Date, n: number): Date {
  const copy = new Date(d);
  copy.setDate(copy.getDate() + n);
  return copy;
}
function formatDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function parseDateOnly(value: string): Date {
  const [y, m, d] = value.split('-').map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

function weekdayCn(d: Date): string {
  return WEEKDAY_CN[d.getDay()] ?? '';
}

/** 展示用：YYYY-MM-DD 星期x */
function dateWithWeekday(d: Date): string {
  return `${formatDate(d)} ${weekdayCn(d)}`;
}

const selectedDateDisplay = computed(() => {
  const parts = selectedDate.value.split('-').map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return selectedDate.value;
  const [y, m, d] = parts;
  return dateWithWeekday(new Date(y, m - 1, d));
});

async function loadEntries() {
  eventsLoading.value = true;
  entriesLoading.value = true;
  error.value = null;
  detail.value = null;
  try {
    const [eventRes, entryRes] = await Promise.all([
      calendarApi.listEventsByDate(selectedDate.value),
      calendarApi.listByDate(selectedDate.value),
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

function selectDate(d: Date) {
  selectedDate.value = formatDate(d);
  void loadEntries();
}

function shiftWeek(step: number) {
  weekStart.value = addDays(weekStart.value, step * 7);
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

function renderMarkdown(content: string | null): string {
  if (!content) return '';
  return renderMarkdownToHtml(content);
}

onMounted(loadEntries);

watch(displayTimezone, () => {
  const previousToday = todayInDisplayTimezone.value;
  const nextToday = getTodayInDisplayTimezone();
  todayInDisplayTimezone.value = nextToday;
  if (selectedDate.value === previousToday) {
    selectedDate.value = nextToday;
    weekStart.value = startOfWeek(parseDateOnly(nextToday));
  }
  void loadEntries();
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
        <p class="text-xs text-secondary-text">按周查看财经事件与自动化任务记录</p>
      </div>
    </div>

    <div class="mb-4 rounded-2xl border border-border/60 bg-card p-4">
      <div class="mb-3 flex items-center justify-between">
        <button class="rounded-lg p-2 hover:bg-hover" @click="shiftWeek(-1)"><ChevronLeft class="h-4 w-4" /></button>
        <p class="text-sm font-medium">当周日历</p>
        <button class="rounded-lg p-2 hover:bg-hover" @click="shiftWeek(1)"><ChevronRight class="h-4 w-4" /></button>
      </div>
      <div class="grid grid-cols-2 gap-1.5 min-[430px]:grid-cols-4 sm:grid-cols-7 sm:gap-2">
        <button
          v-for="d in weekDates"
          :key="formatDate(d)"
          type="button"
          class="flex min-h-14 flex-col items-center justify-center gap-1 rounded-xl border px-2 py-2 text-center leading-tight sm:min-h-16"
          :class="selectedDate === formatDate(d) ? 'border-primary bg-primary/10 text-primary' : 'border-border/60 hover:bg-hover'"
          @click="selectDate(d)"
        >
          <span class="block whitespace-nowrap text-[11px] font-medium sm:text-xs">{{ formatDate(d) }}</span>
          <span
            class="block whitespace-nowrap text-[10px] text-secondary-text sm:text-[11px]"
            :class="selectedDate === formatDate(d) ? 'text-primary' : ''"
          >
            {{ weekdayCn(d) }}
          </span>
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
        <div class="grid grid-cols-1 gap-2 p-1 sm:grid-cols-2 lg:grid-cols-3">
          <article
            v-for="item in events"
            :key="item.id"
            class="rounded-xl border border-border/60 transition hover:border-primary/25 hover:shadow-soft-card"
          >
            <button
              type="button"
              class="flex w-full items-start justify-between gap-3 rounded-xl p-3 text-left transition hover:bg-hover/70"
              @click="openEventDetail(item)"
            >
            <span class="min-w-0 flex-1">
              <span class="mb-1 flex flex-wrap items-center gap-2 text-xs text-secondary-text">
                <span class="rounded-full bg-hover px-2 py-0.5">{{ eventTypeLabel(item.calendar_type) }}</span>
                <span>{{ eventName(item) }}</span>
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
          </article>
        </div>
      </div>
    </div>

    <div class="rounded-2xl border border-border/60 bg-card p-4">
      <h2 class="mb-3 text-xs font-semibold sm:text-sm">{{ selectedDateDisplay }} 日历记录</h2>
      <div v-if="entriesLoading" class="space-y-2"><div v-for="n in 3" :key="n" class="h-12 animate-pulse rounded-xl bg-hover" /></div>
      <div v-else-if="!entries.length" class="py-6 text-sm text-secondary-text">当天暂无日历记录</div>
      <div v-else class="space-y-2 p-1">
        <article
          v-for="item in entries"
          :key="item.id"
          class="rounded-xl border border-border/60 transition hover:border-primary/25 hover:shadow-soft-card"
        >
          <button
            type="button"
            class="flex w-full items-start justify-between gap-3 rounded-xl p-3 text-left transition hover:bg-hover/70"
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
        </article>
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
            <p class="text-xs text-muted-text">评级</p>
            <p class="mt-1 text-sm text-foreground">star {{ detail.item.star }}</p>
          </div>
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">时间</p>
            <p class="mt-1 text-sm text-foreground">{{ eventTime(detail.item) }}</p>
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
