<script setup lang="ts">
import { calendarApi, type CalendarSignalItem } from '@/api/calendar';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-vue-next';
import { marked } from 'marked';
import { computed, onMounted, ref } from 'vue';

const WEEKDAY_CN = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'] as const;

const weekStart = ref(startOfWeek(new Date()));
const selectedDate = ref(formatDate(new Date()));
const signals = ref<CalendarSignalItem[]>([]);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const expandedSignalId = ref<number | null>(null);

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

async function loadSignals() {
  loading.value = true;
  error.value = null;
  expandedSignalId.value = null;
  try {
    const res = await calendarApi.listByDate(selectedDate.value);
    signals.value = res.items;
  } catch (e) {
    error.value = getParsedApiError(e);
  } finally {
    loading.value = false;
  }
}

function selectDate(d: Date) {
  selectedDate.value = formatDate(d);
  void loadSignals();
}

function shiftWeek(step: number) {
  weekStart.value = addDays(weekStart.value, step * 7);
}

function toggleSignal(item: CalendarSignalItem) {
  expandedSignalId.value = expandedSignalId.value === item.id ? null : item.id;
}

function signalTypeLabel(type: string | null): string {
  if (type === 'scheduled_daily') return '定时全量';
  if (type === 'scheduled_us_premarket') return '美股盘前';
  return type || '日历信号';
}

function renderMarkdown(content: string | null): string {
  if (!content) return '';
  try {
    return marked.parse(content, { async: false, gfm: true }) as string;
  } catch {
    return content;
  }
}

onMounted(loadSignals);
</script>

<template>
  <div class="mx-auto w-full px-4 py-6 sm:px-6">
    <div class="mb-6 flex items-center gap-3">
      <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary-gradient text-[hsl(var(--primary-foreground))] shadow-soft-card">
        <CalendarDays class="h-5 w-5" />
      </div>
      <div>
        <h1 class="text-lg font-semibold text-foreground">日历信号</h1>
        <p class="text-xs text-secondary-text">按周查看每日自动化信号与定时任务执行结果</p>
      </div>
    </div>

    <div class="mb-4 rounded-2xl border border-border/60 bg-card p-4">
      <div class="mb-3 flex items-center justify-between">
        <button class="rounded-lg p-2 hover:bg-hover" @click="shiftWeek(-1)"><ChevronLeft class="h-4 w-4" /></button>
        <p class="text-sm font-medium">当周日历</p>
        <button class="rounded-lg p-2 hover:bg-hover" @click="shiftWeek(1)"><ChevronRight class="h-4 w-4" /></button>
      </div>
      <div class="grid grid-cols-7 gap-1.5 sm:gap-2">
        <button
          v-for="d in weekDates"
          :key="formatDate(d)"
          type="button"
          class="flex min-h-16 flex-col items-center justify-center gap-1 rounded-xl border px-1 py-2 text-center text-xs leading-tight"
          :class="selectedDate === formatDate(d) ? 'border-primary bg-primary/10 text-primary' : 'border-border/60 hover:bg-hover'"
          @click="selectDate(d)"
        >
          <span class="block whitespace-nowrap font-medium">{{ formatDate(d) }}</span>
          <span class="block whitespace-nowrap text-secondary-text" :class="selectedDate === formatDate(d) ? 'text-primary' : ''">{{ weekdayCn(d) }}</span>
        </button>
      </div>
    </div>

    <ApiErrorAlert v-if="error" :error="error" class="mb-4" />
    <div class="rounded-2xl border border-border/60 bg-card p-4">
      <h2 class="mb-3 text-sm font-semibold">{{ selectedDateDisplay }} 信号列表</h2>
      <div v-if="loading" class="space-y-2"><div v-for="n in 3" :key="n" class="h-12 animate-pulse rounded-xl bg-hover" /></div>
      <div v-else-if="!signals.length" class="py-6 text-sm text-secondary-text">当天暂无信号数据</div>
      <div v-else class="space-y-2">
        <article v-for="item in signals" :key="item.id" class="overflow-hidden rounded-xl border border-border/60">
          <button
            type="button"
            class="flex w-full items-start justify-between gap-3 p-3 text-left transition hover:bg-hover/70"
            @click="toggleSignal(item)"
          >
            <span class="min-w-0 flex-1">
              <span class="block text-sm font-medium">{{ item.title }}</span>
              <span class="mt-1 flex flex-wrap items-center gap-2 text-xs text-secondary-text">
                <span class="rounded-full bg-hover px-2 py-0.5">{{ signalTypeLabel(item.signal_type) }}</span>
                <span>{{ new Date(item.created_at).toLocaleString() }}</span>
                <span v-if="item.content">点击查看执行结果与报告</span>
              </span>
            </span>
            <ChevronDown
              class="mt-0.5 h-4 w-4 shrink-0 text-secondary-text transition-transform"
              :class="expandedSignalId === item.id ? 'rotate-180 text-primary' : ''"
            />
          </button>
          <div v-if="expandedSignalId === item.id" class="border-t border-border/60 bg-background/40 p-3">
            <div v-if="item.content" class="prose prose-sm max-w-none text-sm text-foreground dark:prose-invert" v-html="renderMarkdown(item.content)" />
            <p v-else class="text-sm text-secondary-text">该记录暂无详情内容</p>
          </div>
        </article>
      </div>
    </div>
  </div>
</template>
