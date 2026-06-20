<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { tasksApi, type TaskRunQuery } from '@/api/tasks';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Badge from '@/components/common/Badge.vue';
import Button from '@/components/common/Button.vue';
import ConfirmDialog from '@/components/common/ConfirmDialog.vue';
import Drawer from '@/components/common/Drawer.vue';
import InlineAlert from '@/components/common/InlineAlert.vue';
import Pagination from '@/components/common/Pagination.vue';
import { formatDocumentTitle } from '@/config/app';
import { useAuthStore } from '@/stores/authStore';
import type { ScheduledTask, TaskRun, TaskRunDetail, TaskStatus } from '@/types/tasks';
import { formatDateTimeInDisplayTimezone, toUtcIsoString } from '@/utils/format';
import {
  ClipboardCheck,
  ClipboardList,
  ChevronDown,
  Copy,
  FileSearch,
  ListChecks,
  Play,
  RotateCw,
} from 'lucide-vue-next';
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { RouterLink, useRoute, useRouter } from 'vue-router';

type TaskTab = 'scheduled' | 'runs';

const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();

const scheduledItems = ref<ScheduledTask[]>([]);
const scheduledLoading = ref(false);
const scheduledError = ref<ParsedApiError | null>(null);
const scheduledSuccess = ref<string | null>(null);
const selectedJob = ref<ScheduledTask | null>(null);
const runningJobId = ref<string | null>(null);

const runs = ref<TaskRun[]>([]);
const runsTotal = ref(0);
const runsPage = ref(1);
const runsPageSize = ref(20);
const runsStats = ref<Record<string, number>>({});
const runsLoading = ref(false);
const runsError = ref<ParsedApiError | null>(null);
const statusFilterMenuRef = ref<HTMLDetailsElement | null>(null);

const detail = ref<TaskRunDetail | null>(null);
const detailLoading = ref(false);
const detailError = ref<ParsedApiError | null>(null);

const taskStatusOptions: Array<{ value: TaskStatus; label: string }> = [
  { value: 'pending', label: '等待中' },
  { value: 'processing', label: '执行中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'skipped', label: '已跳过' },
  { value: 'retrying', label: '重试中' },
  { value: 'cancelled', label: '已取消' },
];
const defaultStatusFilters = taskStatusOptions
  .filter((option) => option.value !== 'skipped')
  .map((option) => option.value);

const filters = reactive<{
  statuses: TaskStatus[];
  taskType: string;
  source: string;
  triggerSource: string;
  keyword: string;
  startedFrom: string;
  startedTo: string;
  uid: string;
}>({
  statuses: [...defaultStatusFilters],
  taskType: '',
  source: '',
  triggerSource: '',
  keyword: '',
  startedFrom: '',
  startedTo: '',
  uid: '',
});

const isAdmin = computed(() => authStore.currentUser?.role === 'admin');
const activeTab = computed<TaskTab>(() => (route.path.endsWith('/scheduled') ? 'scheduled' : 'runs'));
const totalPages = computed(() => Math.max(1, Math.ceil(runsTotal.value / runsPageSize.value)));

const navItems = computed(() => [
  ...(isAdmin.value ? [{ key: 'scheduled' as const, label: '定时任务', icon: ClipboardCheck, to: '/tasks/scheduled' }] : []),
  { key: 'runs' as const, label: '执行记录', icon: ListChecks, to: '/tasks/runs' },
]);

const statusOptions: Array<{ value: TaskStatus | ''; label: string }> = [
  { value: '', label: '全部状态' },
  ...taskStatusOptions,
];

const statusFilterLabel = computed(() => `已选 ${filters.statuses.length} 个状态`);

const sourceOptions = [
  { value: '', label: '全部来源' },
  { value: 'apscheduler', label: 'APScheduler' },
  { value: 'celery_manual', label: 'Celery' },
];

const triggerOptions = [
  { value: '', label: '全部触发' },
  { value: 'scheduler', label: '定时触发' },
  { value: 'manual', label: '管理员手动' },
  { value: 'api', label: 'API 提交' },
  { value: 'bot', label: 'Bot 提交' },
];

function statusLabel(value?: string | null): string {
  const map: Record<string, string> = {
    pending: '等待中',
    processing: '执行中',
    completed: '已完成',
    failed: '失败',
    skipped: '已跳过',
    retrying: '重试中',
    cancelled: '已取消',
  };
  return value ? map[value] ?? value : '从未执行';
}

function statusVariant(value?: string | null): 'default' | 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'completed') return 'success';
  if (value === 'failed') return 'danger';
  if (value === 'processing') return 'info';
  if (value === 'retrying') return 'warning';
  return 'default';
}

function schedulerStatusLabel(value: string): string {
  if (value === 'active') return '正常';
  if (value === 'paused') return '暂停';
  if (value === 'running') return '执行中';
  return '不可用';
}

function triggerLabel(value?: string | null): string {
  return triggerOptions.find((item) => item.value === value)?.label ?? (value || '—');
}

function toggleStatusFilter(status: TaskStatus) {
  if (filters.statuses.includes(status)) {
    if (filters.statuses.length <= 1) return;
    filters.statuses = filters.statuses.filter((item) => item !== status);
    return;
  }
  filters.statuses = [...filters.statuses, status];
}

function selectAllStatuses() {
  filters.statuses = taskStatusOptions.map((option) => option.value);
}

function selectDefaultStatuses() {
  filters.statuses = [...defaultStatusFilters];
}

function closeStatusFilterOnOutsideClick(event: MouseEvent) {
  const menu = statusFilterMenuRef.value;
  const target = event.target;
  if (!menu?.open || !(target instanceof Node) || menu.contains(target)) return;
  menu.open = false;
}

function formatDuration(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return '—';
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes <= 0) return `${rest} 秒`;
  return `${minutes} 分 ${rest} 秒`;
}

function shortTaskId(taskId: string): string {
  if (taskId.length <= 12) return taskId;
  return `${taskId.slice(0, 8)}...${taskId.slice(-4)}`;
}

function formatJson(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

function dateStartIso(value: string): string {
  return toUtcIsoString(`${value}T00:00:00`);
}

function dateEndIso(value: string): string {
  return toUtcIsoString(`${value}T23:59:59`);
}

async function copyText(value?: string | null) {
  if (!value) return;
  await navigator.clipboard?.writeText(value);
}

async function loadScheduled() {
  if (!isAdmin.value) return;
  scheduledLoading.value = true;
  scheduledError.value = null;
  try {
    scheduledItems.value = (await tasksApi.getScheduledTasks()).items;
  } catch (err) {
    scheduledError.value = getParsedApiError(err);
  } finally {
    scheduledLoading.value = false;
  }
}

function buildRunQuery(page = runsPage.value): TaskRunQuery {
  return {
    page,
    pageSize: runsPageSize.value,
    status: filters.statuses.join(',') || undefined,
    taskType: filters.taskType.trim() || undefined,
    source: filters.source || undefined,
    triggerSource: filters.triggerSource || undefined,
    keyword: filters.keyword.trim() || undefined,
    startedFrom: filters.startedFrom ? dateStartIso(filters.startedFrom) : undefined,
    startedTo: filters.startedTo ? dateEndIso(filters.startedTo) : undefined,
    uid: isAdmin.value && filters.uid.trim() ? Number(filters.uid.trim()) : undefined,
  };
}

async function loadRuns(page = runsPage.value) {
  runsLoading.value = true;
  runsError.value = null;
  try {
    const res = await tasksApi.getTaskRuns(buildRunQuery(page));
    runs.value = res.items;
    runsTotal.value = res.total;
    runsPage.value = res.page;
    runsPageSize.value = res.pageSize;
    runsStats.value = res.statistics;
  } catch (err) {
    runsError.value = getParsedApiError(err);
  } finally {
    runsLoading.value = false;
  }
}

function submitFilters() {
  void loadRuns(1);
}

function resetFilters() {
  Object.assign(filters, {
    statuses: [...defaultStatusFilters],
    taskType: '',
    source: '',
    triggerSource: '',
    keyword: '',
    startedFrom: '',
    startedTo: '',
    uid: '',
  });
  void loadRuns(1);
}

async function confirmRunScheduled() {
  if (!selectedJob.value) return;
  const job = selectedJob.value;
  runningJobId.value = job.jobId;
  scheduledError.value = null;
  scheduledSuccess.value = null;
  selectedJob.value = null;
  try {
    await tasksApi.runScheduledTask(job.jobId);
    scheduledSuccess.value = '任务已提交，执行结果可在执行记录中查看。';
    await loadScheduled();
  } catch (err) {
    scheduledError.value = getParsedApiError(err);
  } finally {
    runningJobId.value = null;
  }
}

async function openDetail(item: TaskRun) {
  detail.value = null;
  detailError.value = null;
  detailLoading.value = true;
  try {
    detail.value = await tasksApi.getTaskRunDetail(item.taskId);
  } catch (err) {
    detailError.value = getParsedApiError(err);
  } finally {
    detailLoading.value = false;
  }
}

function routeToDefaultIfNeeded() {
  if (route.path === '/tasks') {
    void router.replace(isAdmin.value ? '/tasks/scheduled' : '/tasks/runs');
    return;
  }
  if (route.path.endsWith('/scheduled') && !isAdmin.value) {
    void router.replace('/tasks/runs');
  }
}

watch(
  () => [route.path, isAdmin.value] as const,
  () => {
    routeToDefaultIfNeeded();
    if (route.path.endsWith('/scheduled') && isAdmin.value) void loadScheduled();
    if (route.path.endsWith('/runs')) void loadRuns(1);
  },
  { immediate: true },
);

onMounted(() => {
  document.title = formatDocumentTitle('任务中心');
  document.addEventListener('click', closeStatusFilterOnOutsideClick);
});

onBeforeUnmount(() => {
  document.removeEventListener('click', closeStatusFilterOnOutsideClick);
});
</script>

<template>
  <div class="space-y-5">
    <div class="flex flex-col gap-1">
      <h1 class="text-xl font-semibold text-foreground">任务中心</h1>
      <p class="text-sm text-muted-text">
        {{ isAdmin ? '查看定时任务定义和全部执行记录。' : '查看自己的任务执行记录。' }}
      </p>
    </div>

    <div class="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
      <aside class="h-fit space-y-1 rounded-2xl border border-border/70 bg-card/94 p-2 shadow-soft-card backdrop-blur-sm">
        <RouterLink
          v-for="item in navItems"
          :key="item.key"
          :to="item.to"
          :class="[
            'flex h-11 w-full items-center gap-2 rounded-xl px-3 text-left text-sm font-medium transition-colors',
            activeTab === item.key
              ? 'bg-primary/12 text-primary'
              : 'text-secondary-text hover:bg-hover hover:text-foreground',
          ]"
        >
          <component :is="item.icon" class="h-4 w-4 shrink-0" />
          <span class="truncate">{{ item.label }}</span>
        </RouterLink>
      </aside>

      <section class="min-w-0 space-y-4">
        <template v-if="activeTab === 'scheduled' && isAdmin">
          <div class="rounded-2xl border border-border/70 bg-card/94 p-4 shadow-soft-card">
            <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div class="flex items-center gap-3">
                <ClipboardCheck class="h-5 w-5 text-primary" />
                <div>
                  <h2 class="text-base font-semibold text-foreground">定时任务</h2>
                  <p class="text-xs text-muted-text">任务定义来自后端 APScheduler 代码注册表。</p>
                </div>
              </div>
              <Button variant="secondary" size="sm" :is-loading="scheduledLoading" @click="loadScheduled">
                <RotateCw class="h-4 w-4" />
                刷新
              </Button>
            </div>
          </div>

          <ApiErrorAlert v-if="scheduledError" :error="scheduledError" @dismiss="scheduledError = null" />
          <InlineAlert v-if="scheduledSuccess" variant="success" title="提交成功">
            {{ scheduledSuccess }}
          </InlineAlert>

          <div class="overflow-x-auto rounded-2xl border border-border/70 bg-card/94 shadow-soft-card">
            <table class="min-w-[980px] w-full text-left text-sm">
              <thead class="border-b border-border/70 text-xs text-muted-text">
                <tr>
                  <th class="px-4 py-3 font-medium">任务</th>
                  <th class="px-4 py-3 font-medium">调度规则</th>
                  <th class="px-4 py-3 font-medium">调度状态</th>
                  <th class="px-4 py-3 font-medium">最近执行</th>
                  <th class="px-4 py-3 font-medium">下次执行</th>
                  <th class="px-4 py-3 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="scheduledLoading">
                  <td colspan="6" class="px-4 py-10 text-center text-muted-text">加载中...</td>
                </tr>
                <tr v-else-if="!scheduledItems.length">
                  <td colspan="6" class="px-4 py-10 text-center text-muted-text">暂无定时任务</td>
                </tr>
                <tr
                  v-for="item in scheduledItems"
                  v-else
                  :key="item.jobId"
                  class="border-b border-border/50 last:border-0"
                >
                  <td class="px-4 py-4">
                    <p class="font-medium text-foreground">{{ item.name }}</p>
                    <p class="mt-1 max-w-xs text-xs text-muted-text">{{ item.description }}</p>
                    <p class="mt-1 font-mono text-[11px] text-muted-text">{{ item.jobId }}</p>
                  </td>
                  <td class="px-4 py-4">
                    <p class="text-foreground">{{ item.schedule }}</p>
                    <p class="mt-1 text-xs text-muted-text">{{ item.timezone }}</p>
                  </td>
                  <td class="px-4 py-4">
                    <Badge :variant="item.schedulerStatus === 'active' ? 'success' : 'default'">
                      {{ schedulerStatusLabel(item.schedulerStatus) }}
                    </Badge>
                  </td>
                  <td class="px-4 py-4">
                    <template v-if="item.latestRun">
                      <Badge :variant="statusVariant(item.latestRun.status)">
                        {{ statusLabel(item.latestRun.status) }}
                      </Badge>
                      <p class="mt-2 text-xs text-muted-text">
                        {{ formatDateTimeInDisplayTimezone(item.latestRun.finishedAt || item.latestRun.startedAt) }}
                      </p>
                      <p class="mt-1 text-xs text-muted-text">{{ formatDuration(item.latestRun.durationSeconds) }}</p>
                    </template>
                    <span v-else class="text-xs text-muted-text">从未执行</span>
                  </td>
                  <td class="px-4 py-4 text-sm text-foreground">
                    {{ formatDateTimeInDisplayTimezone(item.nextRunTime) }}
                  </td>
                  <td class="px-4 py-4 text-right">
                    <Button
                      v-if="item.allowManualRun"
                      variant="secondary"
                      size="sm"
                      :is-loading="runningJobId === item.jobId"
                      :disabled="!!item.latestRun && ['pending', 'processing', 'retrying'].includes(item.latestRun.status)"
                      @click="selectedJob = item"
                    >
                      <Play class="h-4 w-4" />
                      立即执行
                    </Button>
                    <span v-else class="text-xs text-muted-text">不可手动执行</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>

        <template v-else>
          <div class="rounded-2xl border border-border/70 bg-card/94 p-4 shadow-soft-card">
            <div class="space-y-3">
              <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div class="flex items-center gap-3">
                  <ClipboardList class="h-5 w-5 text-primary" />
                  <div>
                    <h2 class="text-base font-semibold text-foreground">执行记录</h2>
                    <p class="text-xs text-muted-text">{{ isAdmin ? '全部用户和系统任务。' : '自己的任务执行记录。' }}</p>
                  </div>
                </div>
                <Button variant="secondary" size="sm" :is-loading="runsLoading" @click="loadRuns(runsPage)">
                  <RotateCw class="h-4 w-4" />
                  刷新
                </Button>
              </div>

              <div class="grid gap-2 sm:grid-cols-2 lg:max-w-[560px]">
                <input
                  v-if="isAdmin"
                  v-model="filters.uid"
                  class="h-9 w-full rounded-xl border border-border/70 bg-background px-3 text-sm"
                  inputmode="numeric"
                  placeholder="UID"
                />
                <input
                  v-model="filters.keyword"
                  class="h-9 w-full rounded-xl border border-border/70 bg-background px-3 text-sm"
                  placeholder="名称或 Task ID"
                />
              </div>

              <div class="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                <details ref="statusFilterMenuRef" class="group relative">
                  <summary
                    class="flex h-9 w-full cursor-pointer list-none items-center justify-between gap-2 rounded-xl border border-border/70 bg-background px-3 text-sm text-foreground transition-colors hover:bg-hover [&::-webkit-details-marker]:hidden"
                  >
                    <span class="truncate">{{ statusFilterLabel }}</span>
                    <ChevronDown class="h-4 w-4 shrink-0 text-secondary-text transition-transform group-open:rotate-180" />
                  </summary>
                  <div class="absolute left-0 top-11 z-20 w-56 rounded-xl border border-border/70 bg-card p-2 shadow-soft-card-strong">
                    <div class="mb-2 flex items-center justify-between gap-2 border-b border-border/60 pb-2">
                      <button
                        type="button"
                        class="rounded-lg px-2 py-1 text-xs font-medium text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
                        @click="selectAllStatuses"
                      >
                        全选
                      </button>
                      <button
                        type="button"
                        class="rounded-lg px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/10"
                        @click="selectDefaultStatuses"
                      >
                        默认
                      </button>
                    </div>
                    <label
                      v-for="option in taskStatusOptions"
                      :key="option.value"
                      class="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-foreground transition-colors hover:bg-hover"
                    >
                      <input
                        class="h-4 w-4 rounded border-border/70 text-primary focus:ring-primary/40"
                        type="checkbox"
                        :checked="filters.statuses.includes(option.value)"
                        :disabled="filters.statuses.length <= 1 && filters.statuses.includes(option.value)"
                        @change="toggleStatusFilter(option.value)"
                      />
                      <span>{{ option.label }}</span>
                    </label>
                  </div>
                </details>
                <input
                  v-model="filters.taskType"
                  class="h-9 w-full rounded-xl border border-border/70 bg-background px-3 text-sm"
                  placeholder="任务类型"
                />
                <select v-model="filters.source" class="h-9 w-full rounded-xl border border-border/70 bg-background px-3 text-sm">
                  <option v-for="option in sourceOptions" :key="option.value" :value="option.value">
                    {{ option.label }}
                  </option>
                </select>
                <select v-model="filters.triggerSource" class="h-9 w-full rounded-xl border border-border/70 bg-background px-3 text-sm">
                  <option v-for="option in triggerOptions" :key="option.value" :value="option.value">
                    {{ option.label }}
                  </option>
                </select>
              </div>

              <div class="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                <div class="grid gap-2 sm:grid-cols-2 lg:w-[360px]">
                  <input
                    v-model="filters.startedFrom"
                    class="h-9 w-full rounded-xl border border-border/70 bg-background px-3 text-sm"
                    type="date"
                    aria-label="开始日期"
                  />
                  <input
                    v-model="filters.startedTo"
                    class="h-9 w-full rounded-xl border border-border/70 bg-background px-3 text-sm"
                    type="date"
                    aria-label="结束日期"
                  />
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <Button variant="secondary" size="sm" @click="submitFilters">查询</Button>
                  <Button variant="ghost" size="sm" @click="resetFilters">重置</Button>
                </div>
              </div>
            </div>

            <div class="mt-4 flex flex-wrap gap-2 text-xs">
              <Badge v-for="option in statusOptions.filter((item) => item.value)" :key="option.value" variant="default">
                {{ option.label }} {{ runsStats[option.value] ?? 0 }}
              </Badge>
            </div>
          </div>

          <ApiErrorAlert v-if="runsError" :error="runsError" @dismiss="runsError = null" />

          <div class="overflow-x-auto rounded-2xl border border-border/70 bg-card/94 shadow-soft-card">
            <table class="w-full min-w-[1320px] text-left text-sm">
              <thead class="border-b border-border/70 text-xs text-muted-text">
                <tr>
                  <th class="min-w-[220px] px-4 py-3 font-medium">任务</th>
                  <th class="min-w-[96px] whitespace-nowrap px-4 py-3 font-medium">状态</th>
                  <th v-if="isAdmin" class="min-w-[112px] whitespace-nowrap px-4 py-3 font-medium">所属用户</th>
                  <th class="min-w-[220px] whitespace-nowrap px-4 py-3 font-medium">来源</th>
                  <th class="min-w-[140px] whitespace-nowrap px-4 py-3 font-medium">提交时间</th>
                  <th class="min-w-[80px] whitespace-nowrap px-4 py-3 font-medium">耗时</th>
                  <th class="min-w-[280px] px-4 py-3 font-medium">消息</th>
                  <th class="min-w-[112px] whitespace-nowrap px-4 py-3 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="runsLoading">
                  <td :colspan="isAdmin ? 8 : 7" class="px-4 py-10 text-center text-muted-text">加载中...</td>
                </tr>
                <tr v-else-if="!runs.length">
                  <td :colspan="isAdmin ? 8 : 7" class="px-4 py-10 text-center text-muted-text">暂无执行记录</td>
                </tr>
                <tr v-for="item in runs" v-else :key="item.taskId" class="border-b border-border/50 last:border-0">
                  <td class="min-w-[220px] px-4 py-4">
                    <p class="font-medium text-foreground">{{ item.taskName || item.taskType }}</p>
                    <p class="mt-1 text-xs text-muted-text">{{ item.taskType }}</p>
                    <p v-if="isAdmin" class="mt-1 font-mono text-[11px] text-muted-text">
                      {{ shortTaskId(item.taskId) }}
                      <button class="ml-1 align-middle text-primary" aria-label="复制 Task ID" @click="copyText(item.taskId)">
                        <Copy class="inline h-3.5 w-3.5" />
                      </button>
                    </p>
                  </td>
                  <td class="min-w-[96px] whitespace-nowrap px-4 py-4">
                    <Badge class="whitespace-nowrap" :variant="statusVariant(item.status)">{{ statusLabel(item.status) }}</Badge>
                  </td>
                  <td v-if="isAdmin" class="min-w-[112px] whitespace-nowrap px-4 py-4 text-xs text-muted-text">
                    <template v-if="item.user">{{ item.user.username }}<br />{{ item.user.email }}</template>
                    <span v-else>系统任务</span>
                  </td>
                  <td class="min-w-[220px] px-4 py-4 text-xs text-muted-text">
                    <p>{{ item.source }}</p>
                    <p>{{ triggerLabel(item.triggerSource) }}</p>
                    <p v-if="isAdmin && item.schedulerJobId" class="font-mono">{{ item.schedulerJobId }}</p>
                  </td>
                  <td class="min-w-[140px] whitespace-nowrap px-4 py-4 text-sm text-foreground">
                    {{ formatDateTimeInDisplayTimezone(item.createdAt) }}
                  </td>
                  <td class="min-w-[80px] whitespace-nowrap px-4 py-4 text-sm text-foreground">{{ formatDuration(item.durationSeconds) }}</td>
                  <td class="min-w-[280px] max-w-xs px-4 py-4 text-xs text-muted-text">
                    <span class="line-clamp-2">{{ item.message || '—' }}</span>
                  </td>
                  <td class="min-w-[112px] whitespace-nowrap px-4 py-4 text-right">
                    <Button variant="ghost" size="sm" @click="openDetail(item)">
                      <FileSearch class="h-4 w-4" />
                      查看详情
                    </Button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <Pagination
            :current-page="runsPage"
            :total-pages="totalPages"
            class="pt-2"
            @page-change="loadRuns"
          />
        </template>
      </section>
    </div>

    <Drawer
      :is-open="detailLoading || !!detail || !!detailError"
      title="任务详情"
      width="max-w-4xl"
      variant="modal"
      @close="detail = null; detailError = null"
    >
      <div v-if="detailLoading" class="py-10 text-center text-sm text-muted-text">加载中...</div>
      <ApiErrorAlert v-else-if="detailError" :error="detailError" @dismiss="detailError = null" />
      <div v-else-if="detail" class="space-y-5">
        <div class="grid gap-3 sm:grid-cols-2">
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">任务名称</p>
            <p class="mt-1 text-sm font-medium text-foreground">{{ detail.taskName || detail.taskType }}</p>
          </div>
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">状态</p>
            <Badge class="mt-1" :variant="statusVariant(detail.status)">{{ statusLabel(detail.status) }}</Badge>
          </div>
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">Task ID</p>
            <p class="mt-1 break-all font-mono text-xs text-foreground">{{ detail.taskId }}</p>
          </div>
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">任务类型</p>
            <p class="mt-1 text-sm text-foreground">{{ detail.taskType }}</p>
          </div>
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">来源 / 触发</p>
            <p class="mt-1 text-sm text-foreground">{{ detail.source }} / {{ triggerLabel(detail.triggerSource) }}</p>
          </div>
          <div class="rounded-xl border border-border/60 bg-background/60 p-3">
            <p class="text-xs text-muted-text">耗时</p>
            <p class="mt-1 text-sm text-foreground">{{ formatDuration(detail.durationSeconds) }}</p>
          </div>
        </div>

        <div class="rounded-xl border border-border/60 bg-background/60 p-3">
          <p class="text-xs text-muted-text">执行时间</p>
          <div class="mt-2 grid gap-2 text-sm text-foreground sm:grid-cols-2">
            <p>创建：{{ formatDateTimeInDisplayTimezone(detail.createdAt) }}</p>
            <p>开始：{{ formatDateTimeInDisplayTimezone(detail.startedAt) }}</p>
            <p>结束：{{ formatDateTimeInDisplayTimezone(detail.finishedAt) }}</p>
            <p>更新：{{ formatDateTimeInDisplayTimezone(detail.updatedAt) }}</p>
          </div>
        </div>

        <div class="rounded-xl border border-border/60 bg-background/60 p-3">
          <p class="text-xs text-muted-text">Message</p>
          <p class="mt-2 whitespace-pre-wrap text-sm text-foreground">{{ detail.message || '—' }}</p>
        </div>

        <details class="rounded-xl border border-border/60 bg-background/60 p-3">
          <summary class="cursor-pointer text-sm font-medium text-foreground">Payload</summary>
          <pre class="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs text-secondary-text">{{ formatJson(detail.payload) }}</pre>
        </details>
        <details class="rounded-xl border border-border/60 bg-background/60 p-3">
          <summary class="cursor-pointer text-sm font-medium text-foreground">Result</summary>
          <pre class="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs text-secondary-text">{{ formatJson(detail.result) }}</pre>
        </details>
        <details v-if="detail.error" class="rounded-xl border border-danger/30 bg-danger/5 p-3">
          <summary class="cursor-pointer text-sm font-medium text-danger">错误信息</summary>
          <pre class="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs text-danger">{{ detail.error }}</pre>
        </details>
        <div v-if="isAdmin && detail.taskLog" class="rounded-xl border border-border/60 bg-background/60 p-3">
          <p class="text-xs text-muted-text">Task Log</p>
          <p class="mt-2 break-all font-mono text-xs text-foreground">{{ detail.taskLog }}</p>
        </div>
      </div>
    </Drawer>

    <ConfirmDialog
      :is-open="!!selectedJob"
      title="立即执行定时任务"
      :message="selectedJob ? `确认立即执行“${selectedJob.name}”吗？任务将在后台运行，执行结果可在执行记录中查看。` : ''"
      confirm-text="立即执行"
      cancel-text="取消"
      @confirm="confirmRunScheduled"
      @cancel="selectedJob = null"
    />
  </div>
</template>
