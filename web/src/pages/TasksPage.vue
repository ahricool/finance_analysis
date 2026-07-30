<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { tasksApi, type TaskRunQuery } from '@/api/tasks';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import LoadingButton from '@/components/app/LoadingButton.vue';
import ConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import Pagination from '@/components/app/AppPagination.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import ModuleTabs from '@/components/layout/ModuleTabs.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { useAuthStore } from '@/stores/authStore';
import type {
  ScheduledSyncMode,
  ScheduledTask,
  TaskRun,
  TaskRunDetail,
  TaskStatus,
} from '@/types/tasks';
import { formatDateTimeInDisplayTimezone, toUtcIsoString } from '@/utils/format';
import {
  ClipboardCheck,
  ClipboardList,
  ChevronDown,
  Copy,
  ListChecks,
  Play,
  RotateCw,
} from 'lucide-vue-next';
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

type TaskTab = 'scheduled' | 'runs';

const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();

const scheduledItems = ref<ScheduledTask[]>([]);
const scheduledLoading = ref(false);
const scheduledError = ref<ParsedApiError | null>(null);
const scheduledSuccess = ref<string | null>(null);
const selectedJob = ref<ScheduledTask | null>(null);
const selectedSyncMode = ref<ScheduledSyncMode | null>(null);
const runningJobId = ref<string | null>(null);

const runs = ref<TaskRun[]>([]);
const runsTotal = ref(0);
const runsPage = ref(1);
const runsPageSize = ref(10);
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
const activeTab = computed<TaskTab>(() =>
  route.path.endsWith('/scheduled') ? 'scheduled' : 'runs',
);
const totalPages = computed(() => Math.max(1, Math.ceil(runsTotal.value / runsPageSize.value)));

const navItems = computed(() => [
  ...(isAdmin.value
    ? [
        {
          key: 'scheduled' as const,
          label: '定时任务',
          icon: ClipboardCheck,
          to: '/tasks/scheduled',
        },
      ]
    : []),
  { key: 'runs' as const, label: '执行记录', icon: ListChecks, to: '/tasks/runs' },
]);

const statusOptions: Array<{ value: TaskStatus | ''; label: string }> = [
  { value: '', label: '全部状态' },
  ...taskStatusOptions,
];

const statusFilterLabel = computed(() => `已选 ${filters.statuses.length} 个状态`);

const sourceOptions = [
  { value: '', label: '全部来源' },
  { value: 'celery', label: '定时任务' },
  { value: 'celery_manual', label: '手动 / 分析' },
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
  return value ? (map[value] ?? value) : '从未执行';
}

function statusVariant(
  value?: string | null,
): 'default' | 'success' | 'warning' | 'destructive' | 'info' {
  if (value === 'completed') return 'success';
  if (value === 'failed') return 'destructive';
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
  const syncMode = selectedSyncMode.value;
  runningJobId.value = job.jobId;
  scheduledError.value = null;
  scheduledSuccess.value = null;
  selectedJob.value = null;
  selectedSyncMode.value = null;
  try {
    await tasksApi.runScheduledTask(job.jobId, syncMode ?? undefined);
    const modeLabel =
      syncMode === 'full' ? '全量同步' : syncMode === 'incremental' ? '增量同步' : '';
    scheduledSuccess.value = `${modeLabel ? `${modeLabel}任务` : '任务'}已提交，执行结果可在执行记录中查看。`;
    await loadScheduled();
  } catch (err) {
    scheduledError.value = getParsedApiError(err);
  } finally {
    runningJobId.value = null;
  }
}

function selectScheduledJob(job: ScheduledTask, syncMode: ScheduledSyncMode | null = null) {
  selectedJob.value = job;
  selectedSyncMode.value = syncMode;
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
  document.addEventListener('click', closeStatusFilterOnOutsideClick);
});

onBeforeUnmount(() => {
  document.removeEventListener('click', closeStatusFilterOnOutsideClick);
});
</script>

<template>
  <div class="space-y-6 py-4 sm:py-6">
    <PageHeader
      title="任务中心"
      :description="isAdmin ? '查看定时任务定义和全部执行记录。' : '查看自己的任务执行记录。'"
    />
    <ModuleTabs
      :items="navItems"
      :active-key="activeTab"
      label="任务中心导航"
    />
    <Separator />

    <section class="min-w-0 space-y-4">
      <template v-if="activeTab === 'scheduled' && isAdmin">
        <Card>
          <CardHeader>
            <div class="flex items-center gap-3">
              <ClipboardCheck class="h-5 w-5 text-primary" />
              <div>
                <CardTitle>定时任务</CardTitle>
                <CardDescription>任务定义来自后端 APScheduler 代码注册表。</CardDescription>
              </div>
            </div>
            <CardAction>
              <LoadingButton
                variant="secondary"
                size="sm"
                :loading="scheduledLoading"
                @click="loadScheduled"
              >
                <RotateCw class="h-4 w-4" />
                刷新
              </LoadingButton>
            </CardAction>
          </CardHeader>
        </Card>

        <ApiErrorAlert
          v-if="scheduledError"
          :error="scheduledError"
          @dismiss="scheduledError = null"
        />
        <Alert
          v-if="scheduledSuccess"
          variant="success"
        >
          <AlertTitle>提交成功</AlertTitle><AlertDescription class="text-current/80">
            {{ scheduledSuccess }}
          </AlertDescription>
        </Alert>

        <div
          class="space-y-3 md:hidden"
          data-testid="scheduled-task-cards"
        >
          <template v-if="scheduledLoading">
            <Skeleton
              v-for="index in 3"
              :key="index"
              class="h-40 w-full"
            />
          </template>
          <Card
            v-for="item in scheduledItems"
            v-else
            :key="item.jobId"
          >
            <CardHeader>
              <CardTitle class="text-base">
                {{ item.name }}
              </CardTitle>
              <CardDescription>{{ item.description }}</CardDescription>
              <Badge :variant="item.schedulerStatus === 'active' ? 'success' : 'default'">
                {{ schedulerStatusLabel(item.schedulerStatus) }}
              </Badge>
            </CardHeader>
            <CardContent class="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p class="text-xs text-muted-foreground">
                  调度规则
                </p><p class="mt-1">
                  {{ item.schedule }}
                </p>
              </div>
              <div>
                <p class="text-xs text-muted-foreground">
                  下次执行
                </p><p class="mt-1">
                  {{ formatDateTimeInDisplayTimezone(item.nextRunTime) }}
                </p>
              </div>
            </CardContent>
            <CardContent
              v-if="item.allowManualRun"
              class="flex flex-wrap gap-2 pt-0"
            >
              <LoadingButton
                size="sm"
                :loading="runningJobId === item.jobId"
                @click="selectScheduledJob(item, item.syncModes?.length ? 'incremental' : null)"
              >
                <Play />立即执行
              </LoadingButton>
              <Button
                v-if="item.syncModes?.length"
                size="sm"
                variant="outline"
                @click="selectScheduledJob(item, 'full')"
              >
                全量同步
              </Button>
            </CardContent>
          </Card>
        </div>

        <div class="hidden overflow-x-auto rounded-lg border md:block">
          <table class="w-full min-w-[1080px] text-left text-sm">
            <thead class="border-b border-border/70 text-xs text-muted-foreground">
              <tr>
                <th class="min-w-[260px] px-4 py-3 font-medium">
                  任务
                </th>
                <th class="min-w-[180px] whitespace-nowrap px-4 py-3 font-medium">
                  调度规则
                </th>
                <th class="min-w-[110px] whitespace-nowrap px-4 py-3 font-medium">
                  调度状态
                </th>
                <th class="min-w-[180px] whitespace-nowrap px-4 py-3 font-medium">
                  最近执行
                </th>
                <th class="min-w-[160px] whitespace-nowrap px-4 py-3 font-medium">
                  下次执行
                </th>
                <th class="min-w-[120px] whitespace-nowrap px-4 py-3 font-medium">
                  操作
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="scheduledLoading">
                <td
                  colspan="6"
                  class="px-4 py-10 text-center text-muted-foreground"
                >
                  加载中...
                </td>
              </tr>
              <tr v-else-if="!scheduledItems.length">
                <td
                  colspan="6"
                  class="px-4 py-10 text-center text-muted-foreground"
                >
                  暂无定时任务
                </td>
              </tr>
              <tr
                v-for="item in scheduledItems"
                v-else
                :key="item.jobId"
                class="border-b border-border/50 last:border-0"
              >
                <td class="min-w-[260px] px-4 py-4">
                  <p class="font-medium text-foreground">
                    {{ item.name }}
                  </p>
                  <p class="mt-1 text-xs text-muted-foreground">
                    {{ item.description }}
                  </p>
                  <p class="mt-1 font-mono text-[11px] text-muted-foreground">
                    {{ item.jobId }}
                  </p>
                </td>
                <td class="min-w-[180px] px-4 py-4">
                  <p class="whitespace-nowrap text-foreground">
                    {{ item.schedule }}
                  </p>
                  <p class="mt-1 whitespace-nowrap text-xs text-muted-foreground">
                    {{ item.timezone }}
                  </p>
                </td>
                <td class="min-w-[110px] whitespace-nowrap px-4 py-4">
                  <Badge
                    class="whitespace-nowrap"
                    :variant="item.schedulerStatus === 'active' ? 'success' : 'default'"
                  >
                    {{ schedulerStatusLabel(item.schedulerStatus) }}
                  </Badge>
                </td>
                <td class="min-w-[180px] px-4 py-4">
                  <template v-if="item.latestRun">
                    <Badge
                      class="whitespace-nowrap"
                      :variant="statusVariant(item.latestRun.status)"
                    >
                      {{ statusLabel(item.latestRun.status) }}
                    </Badge>
                    <p class="mt-2 whitespace-nowrap text-xs text-muted-foreground">
                      {{
                        formatDateTimeInDisplayTimezone(
                          item.latestRun.finishedAt || item.latestRun.startedAt,
                        )
                      }}
                    </p>
                    <p class="mt-1 whitespace-nowrap text-xs text-muted-foreground">
                      {{ formatDuration(item.latestRun.durationSeconds) }}
                    </p>
                  </template>
                  <span
                    v-else
                    class="text-xs text-muted-foreground"
                  >从未执行</span>
                </td>
                <td class="min-w-[160px] whitespace-nowrap px-4 py-4 text-sm text-foreground">
                  {{ formatDateTimeInDisplayTimezone(item.nextRunTime) }}
                </td>
                <td class="min-w-[120px] px-4 py-4">
                  <div
                    v-if="item.allowManualRun"
                    class="flex items-center gap-2 whitespace-nowrap"
                  >
                    <template v-if="item.syncModes?.length">
                      <LoadingButton
                        variant="secondary"
                        size="sm"
                        :loading="runningJobId === item.jobId"
                        :disabled="
                          !!item.latestRun &&
                            ['pending', 'processing', 'retrying'].includes(item.latestRun.status)
                        "
                        @click="selectScheduledJob(item, 'incremental')"
                      >
                        <Play class="h-4 w-4" />
                        增量同步
                      </LoadingButton>
                      <Button
                        variant="ghost"
                        size="sm"
                        :disabled="
                          !!runningJobId ||
                            (!!item.latestRun &&
                              ['pending', 'processing', 'retrying'].includes(item.latestRun.status))
                        "
                        @click="selectScheduledJob(item, 'full')"
                      >
                        全量同步
                      </Button>
                    </template>
                    <LoadingButton
                      v-else
                      variant="secondary"
                      size="sm"
                      :loading="runningJobId === item.jobId"
                      :disabled="
                        !!item.latestRun &&
                          ['pending', 'processing', 'retrying'].includes(item.latestRun.status)
                      "
                      @click="selectScheduledJob(item)"
                    >
                      <Play class="h-4 w-4" />
                      立即执行
                    </LoadingButton>
                  </div>
                  <span
                    v-else
                    class="whitespace-nowrap text-xs text-muted-foreground"
                  >不可手动执行</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <template v-else>
        <Card>
          <CardHeader>
            <div class="flex items-center gap-3">
              <ClipboardList class="h-5 w-5 text-primary" />
              <div>
                <CardTitle>执行记录</CardTitle>
                <CardDescription>
                  {{ isAdmin ? '全部用户和系统任务。' : '自己的任务执行记录。' }}
                </CardDescription>
              </div>
            </div>
            <CardAction>
              <LoadingButton
                variant="secondary"
                size="sm"
                :loading="runsLoading"
                @click="loadRuns(runsPage)"
              >
                <RotateCw class="h-4 w-4" />
                刷新
              </LoadingButton>
            </CardAction>
          </CardHeader>
          <CardContent class="space-y-4">
            <div class="grid gap-2 sm:grid-cols-2 lg:max-w-[560px]">
              <Input
                v-if="isAdmin"
                v-model="filters.uid"
                inputmode="numeric"
                placeholder="UID"
              />
              <Input
                v-model="filters.keyword"
                placeholder="名称或 Task ID"
              />
            </div>

            <div class="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
              <details
                ref="statusFilterMenuRef"
                class="group relative"
              >
                <summary
                  class="flex h-9 w-full cursor-pointer list-none items-center justify-between gap-2 rounded-xl border border-border/70 bg-background px-3 text-sm text-foreground transition-colors hover:bg-muted [&::-webkit-details-marker]:hidden"
                >
                  <span class="truncate">{{ statusFilterLabel }}</span>
                  <ChevronDown
                    class="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
                  />
                </summary>
                <div
                  class="absolute left-0 top-11 z-20 w-56 rounded-xl border border-border/70 bg-card p-2 shadow-xl"
                >
                  <div
                    class="mb-2 flex items-center justify-between gap-2 border-b border-border/60 pb-2"
                  >
                    <button
                      type="button"
                      class="rounded-lg px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
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
                    class="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-foreground transition-colors hover:bg-muted"
                  >
                    <input
                      class="h-4 w-4 rounded border-border/70 text-primary focus:ring-primary/40"
                      type="checkbox"
                      :checked="filters.statuses.includes(option.value)"
                      :disabled="
                        filters.statuses.length <= 1 && filters.statuses.includes(option.value)
                      "
                      @change="toggleStatusFilter(option.value)"
                    />
                    <span>{{ option.label }}</span>
                  </label>
                </div>
              </details>
              <FieldInput
                v-model="filters.taskType"
                placeholder="任务类型"
              />
              <FieldSelect
                v-model="filters.source"
                :options="sourceOptions"
              />
              <FieldSelect
                v-model="filters.triggerSource"
                :options="triggerOptions"
              />
            </div>

            <div class="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
              <div class="grid gap-2 sm:grid-cols-2 lg:w-[360px]">
                <AppDatePicker
                  v-model="filters.startedFrom"
                  placeholder="开始日期"
                />
                <AppDatePicker
                  v-model="filters.startedTo"
                  placeholder="结束日期"
                />
              </div>
              <div class="flex flex-wrap items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  @click="submitFilters"
                >
                  查询
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  @click="resetFilters"
                >
                  重置
                </Button>
              </div>
            </div>
            <Separator />
            <div class="flex flex-wrap gap-2 text-xs">
              <Badge
                v-for="option in statusOptions.filter((item) => item.value)"
                :key="option.value"
                variant="default"
              >
                {{ option.label }} {{ runsStats[option.value] ?? 0 }}
              </Badge>
            </div>
          </CardContent>
        </Card>

        <ApiErrorAlert
          v-if="runsError"
          :error="runsError"
          @dismiss="runsError = null"
        />

        <div
          class="space-y-3 md:hidden"
          data-testid="task-run-cards"
        >
          <template v-if="runsLoading">
            <Skeleton
              v-for="index in 4"
              :key="index"
              class="h-36 w-full"
            />
          </template>
          <Card
            v-for="item in runs"
            v-else
            :key="item.taskId"
          >
            <CardHeader>
              <CardTitle class="text-base">
                {{ item.taskName || item.taskType }}
              </CardTitle>
              <CardDescription>{{ item.source }} · {{ formatDateTimeInDisplayTimezone(item.createdAt) }}</CardDescription>
              <Badge :variant="statusVariant(item.status)">
                {{ statusLabel(item.status) }}
              </Badge>
            </CardHeader>
            <CardContent class="text-sm text-muted-foreground">
              <p class="line-clamp-3">
                {{ item.message || '暂无执行消息' }}
              </p>
            </CardContent>
            <CardContent class="pt-0">
              <Button
                variant="outline"
                size="sm"
                class="w-full"
                @click="openDetail(item)"
              >
                查看详情
              </Button>
            </CardContent>
          </Card>
        </div>

        <div class="hidden overflow-x-auto rounded-lg border md:block">
          <table class="w-full min-w-[1320px] text-left text-sm">
            <thead class="border-b border-border/70 text-xs text-muted-foreground">
              <tr>
                <th class="min-w-[220px] px-4 py-3 font-medium">
                  任务
                </th>
                <th class="min-w-[96px] whitespace-nowrap px-4 py-3 font-medium">
                  状态
                </th>
                <th
                  v-if="isAdmin"
                  class="min-w-[112px] whitespace-nowrap px-4 py-3 font-medium"
                >
                  所属用户
                </th>
                <th class="min-w-[220px] whitespace-nowrap px-4 py-3 font-medium">
                  来源
                </th>
                <th class="min-w-[140px] whitespace-nowrap px-4 py-3 font-medium">
                  提交时间
                </th>
                <th class="min-w-[80px] whitespace-nowrap px-4 py-3 font-medium">
                  耗时
                </th>
                <th class="min-w-[280px] px-4 py-3 font-medium">
                  消息
                </th>
                <th class="min-w-[112px] whitespace-nowrap px-4 py-3 font-medium">
                  操作
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="runsLoading">
                <td
                  :colspan="isAdmin ? 8 : 7"
                  class="px-4 py-10 text-center text-muted-foreground"
                >
                  加载中...
                </td>
              </tr>
              <tr v-else-if="!runs.length">
                <td
                  :colspan="isAdmin ? 8 : 7"
                  class="px-4 py-10 text-center text-muted-foreground"
                >
                  暂无执行记录
                </td>
              </tr>
              <tr
                v-for="item in runs"
                v-else
                :key="item.taskId"
                class="border-b border-border/50 last:border-0"
              >
                <td class="min-w-[220px] px-4 py-4">
                  <p class="font-medium text-foreground">
                    {{ item.taskName || item.taskType }}
                  </p>
                  <p class="mt-1 text-xs text-muted-foreground">
                    {{ item.taskType }}
                  </p>
                  <p
                    v-if="isAdmin"
                    class="mt-1 font-mono text-[11px] text-muted-foreground"
                  >
                    {{ shortTaskId(item.taskId) }}
                    <button
                      class="ml-1 align-middle text-primary"
                      aria-label="复制 Task ID"
                      @click="copyText(item.taskId)"
                    >
                      <Copy class="inline h-3.5 w-3.5" />
                    </button>
                  </p>
                </td>
                <td class="min-w-[96px] whitespace-nowrap px-4 py-4">
                  <Badge
                    class="whitespace-nowrap"
                    :variant="statusVariant(item.status)"
                  >
                    {{ statusLabel(item.status) }}
                  </Badge>
                </td>
                <td
                  v-if="isAdmin"
                  class="min-w-[112px] whitespace-nowrap px-4 py-4 text-xs text-muted-foreground"
                >
                  <template v-if="item.user">
                    {{ item.user.username }}<br />{{ item.user.email }}
                  </template>
                  <span v-else>系统任务</span>
                </td>
                <td class="min-w-[220px] px-4 py-4 text-xs text-muted-foreground">
                  <p>{{ item.source }}</p>
                  <p>{{ triggerLabel(item.triggerSource) }}</p>
                  <p
                    v-if="isAdmin && item.schedulerJobId"
                    class="font-mono"
                  >
                    {{ item.schedulerJobId }}
                  </p>
                </td>
                <td class="min-w-[140px] whitespace-nowrap px-4 py-4 text-sm text-foreground">
                  {{ formatDateTimeInDisplayTimezone(item.createdAt) }}
                </td>
                <td class="min-w-[80px] whitespace-nowrap px-4 py-4 text-sm text-foreground">
                  {{ formatDuration(item.durationSeconds) }}
                </td>
                <td class="min-w-[280px] max-w-xs px-4 py-4 text-xs text-muted-foreground">
                  <span class="line-clamp-2">{{ item.message || '—' }}</span>
                </td>
                <td class="min-w-[112px] whitespace-nowrap px-4 py-4">
                  <Button
                    variant="ghost"
                    size="sm"
                    @click="openDetail(item)"
                  >
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

    <Dialog
      :open="detailLoading || !!detail || !!detailError"
      @update:open="
        detail = null;
        detailError = null;
      "
    >
      <DialogContent class="flex max-h-[calc(100dvh-1rem)] w-[calc(100%-1rem)] max-w-4xl flex-col gap-0 overflow-hidden p-0">
        <DialogHeader class="p-6 text-left">
          <DialogTitle>任务详情</DialogTitle>
          <DialogDescription>查看任务状态、执行时间、输入和输出。</DialogDescription>
        </DialogHeader>
        <Separator />
        <ScrollArea class="min-h-0 flex-1">
          <div class="p-6">
            <div
              v-if="detailLoading"
              class="space-y-3"
            >
              <Skeleton
                v-for="index in 6"
                :key="index"
                class="h-16 w-full"
              />
            </div>
            <ApiErrorAlert
              v-else-if="detailError"
              :error="detailError"
              @dismiss="detailError = null"
            />
            <div
              v-else-if="detail"
              class="space-y-5"
            >
              <div class="grid gap-3 sm:grid-cols-2">
                <div class="rounded-xl border border-border/60 bg-background/60 p-3">
                  <p class="text-xs text-muted-foreground">
                    任务名称
                  </p>
                  <p class="mt-1 text-sm font-medium text-foreground">
                    {{ detail.taskName || detail.taskType }}
                  </p>
                </div>
                <div class="rounded-xl border border-border/60 bg-background/60 p-3">
                  <p class="text-xs text-muted-foreground">
                    状态
                  </p>
                  <Badge
                    class="mt-1"
                    :variant="statusVariant(detail.status)"
                  >
                    {{ statusLabel(detail.status) }}
                  </Badge>
                </div>
                <div class="rounded-xl border border-border/60 bg-background/60 p-3">
                  <p class="text-xs text-muted-foreground">
                    Task ID
                  </p>
                  <p class="mt-1 break-all font-mono text-xs text-foreground">
                    {{ detail.taskId }}
                  </p>
                </div>
                <div class="rounded-xl border border-border/60 bg-background/60 p-3">
                  <p class="text-xs text-muted-foreground">
                    任务类型
                  </p>
                  <p class="mt-1 text-sm text-foreground">
                    {{ detail.taskType }}
                  </p>
                </div>
                <div class="rounded-xl border border-border/60 bg-background/60 p-3">
                  <p class="text-xs text-muted-foreground">
                    来源 / 触发
                  </p>
                  <p class="mt-1 text-sm text-foreground">
                    {{ detail.source }} / {{ triggerLabel(detail.triggerSource) }}
                  </p>
                </div>
                <div class="rounded-xl border border-border/60 bg-background/60 p-3">
                  <p class="text-xs text-muted-foreground">
                    耗时
                  </p>
                  <p class="mt-1 text-sm text-foreground">
                    {{ formatDuration(detail.durationSeconds) }}
                  </p>
                </div>
              </div>

              <div class="rounded-xl border border-border/60 bg-background/60 p-3">
                <p class="text-xs text-muted-foreground">
                  执行时间
                </p>
                <div class="mt-2 grid gap-2 text-sm text-foreground sm:grid-cols-2">
                  <p>创建：{{ formatDateTimeInDisplayTimezone(detail.createdAt) }}</p>
                  <p>开始：{{ formatDateTimeInDisplayTimezone(detail.startedAt) }}</p>
                  <p>结束：{{ formatDateTimeInDisplayTimezone(detail.finishedAt) }}</p>
                  <p>更新：{{ formatDateTimeInDisplayTimezone(detail.updatedAt) }}</p>
                </div>
              </div>

              <div class="rounded-xl border border-border/60 bg-background/60 p-3">
                <p class="text-xs text-muted-foreground">
                  Message
                </p>
                <p class="mt-2 whitespace-pre-wrap text-sm text-foreground">
                  {{ detail.message || '—' }}
                </p>
              </div>

              <details class="rounded-xl border border-border/60 bg-background/60 p-3">
                <summary class="cursor-pointer text-sm font-medium text-foreground">
                  Payload
                </summary>
                <pre
                  class="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs text-muted-foreground"
                >{{ formatJson(detail.payload) }}</pre>
              </details>
              <details class="rounded-xl border border-border/60 bg-background/60 p-3">
                <summary class="cursor-pointer text-sm font-medium text-foreground">
                  Result
                </summary>
                <pre
                  class="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs text-muted-foreground"
                >{{ formatJson(detail.result) }}</pre>
              </details>
              <details
                v-if="detail.error"
                class="rounded-xl border border-destructive/30 bg-destructive/5 p-3"
              >
                <summary class="cursor-pointer text-sm font-medium text-destructive">
                  错误信息
                </summary>
                <pre
                  class="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs text-destructive"
                >{{ detail.error }}</pre>
              </details>
              <div
                v-if="isAdmin && detail.taskLog"
                class="rounded-xl border border-border/60 bg-background/60 p-3"
              >
                <p class="text-xs text-muted-foreground">
                  Task Log
                </p>
                <p class="mt-2 break-all font-mono text-xs text-foreground">
                  {{ detail.taskLog }}
                </p>
              </div>
            </div>
          </div>
        </ScrollArea>
        <Separator />
        <DialogFooter class="p-4 sm:p-6">
          <Button
            variant="outline"
            @click="detail = null; detailError = null"
          >
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <ConfirmDialog
      :open="!!selectedJob"
      title="立即执行定时任务"
      :description="
        selectedJob
          ? `确认立即执行“${selectedJob.name}”${selectedSyncMode === 'full' ? '全量同步' : selectedSyncMode === 'incremental' ? '增量同步' : ''}吗？任务将在后台运行，执行结果可在执行记录中查看。`
          : ''
      "
      confirm-text="立即执行"
      cancel-text="取消"
      @confirm="confirmRunScheduled"
      @update:open="
        selectedJob = null;
        selectedSyncMode = null;
      "
    />
  </div>
</template>
