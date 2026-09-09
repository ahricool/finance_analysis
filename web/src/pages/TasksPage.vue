<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { tasksApi, type TaskRunQuery } from '@/api/tasks';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import AppPagination from '@/components/app/AppPagination.vue';
import LoadingButton from '@/components/app/LoadingButton.vue';
import ModuleTabs from '@/components/layout/ModuleTabs.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import ScheduledTaskDetailDialog from '@/components/tasks/ScheduledTaskDetailDialog.vue';
import TaskRunDetailDialog from '@/components/tasks/TaskRunDetailDialog.vue';
import {
  DEFAULT_RUN_STATUS_FILTERS,
  TASK_STATUS_OPTIONS,
  formatDuration,
  isJobInFlight,
  jobStatusLabel,
  jobStatusVariant,
  runStatusLabel,
  runStatusVariant,
  truncateText,
} from '@/components/tasks/taskPresentation';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useAuthStore } from '@/stores/authStore';
import type {
  ScheduledSyncMode,
  ScheduledTask,
  TaskRun,
  TaskRunDetail,
  TaskStatus,
} from '@/types/tasks';
import { formatDateTimeInDisplayTimezone, toUtcIsoString } from '@/utils/format';
import { ClipboardCheck, ListChecks, RefreshCcw, Search, SlidersHorizontal } from 'lucide-vue-next';
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { toast } from 'vue-sonner';

type TaskTab = 'scheduled' | 'runs';

const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();

const scheduledItems = ref<ScheduledTask[]>([]);
const scheduledLoading = ref(false);
const scheduledError = ref<ParsedApiError | null>(null);
const scheduledDetail = ref<ScheduledTask | null>(null);
const pendingJob = ref<ScheduledTask | null>(null);
const pendingSyncMode = ref<ScheduledSyncMode | null>(null);
const runningJobId = ref<string | null>(null);

const runs = ref<TaskRun[]>([]);
const runsTotal = ref(0);
const runsPage = ref(1);
const runsPageSize = ref(10);
const runsStats = ref<Record<string, number>>({});
const runsLoading = ref(false);
const runsError = ref<ParsedApiError | null>(null);

const detail = ref<TaskRunDetail | null>(null);
const detailOpen = ref(false);
const detailLoading = ref(false);
const detailError = ref<ParsedApiError | null>(null);

const filters = reactive({
  statuses: [...DEFAULT_RUN_STATUS_FILTERS] as TaskStatus[],
  taskType: '',
  keyword: '',
  startedFrom: '',
  startedTo: '',
});

let keywordTimer: ReturnType<typeof setTimeout> | null = null;

const isAdmin = computed(() => authStore.currentUser?.role === 'admin');
const activeTab = computed<TaskTab>(() => (route.path.endsWith('/scheduled') ? 'scheduled' : 'runs'));
const totalPages = computed(() => Math.max(1, Math.ceil(runsTotal.value / runsPageSize.value)));
const pageError = computed(() => (activeTab.value === 'scheduled' ? scheduledError.value : runsError.value));

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

const scheduledOverview = computed(() => {
  let ok = 0;
  let running = 0;
  let issue = 0;
  for (const job of scheduledItems.value) {
    if (isJobInFlight(job)) {
      running += 1;
      continue;
    }
    if (
      job.schedulerStatus === 'paused'
      || job.schedulerStatus === 'unavailable'
      || job.latestRun?.status === 'failed'
    ) {
      issue += 1;
      continue;
    }
    ok += 1;
  }
  return { total: scheduledItems.value.length, ok, running, issue };
});

const runOverview = computed(() => ({
  total: runsTotal.value,
  running: (runsStats.value.processing || 0) + (runsStats.value.pending || 0) + (runsStats.value.retrying || 0),
  success: runsStats.value.completed || 0,
  failed: runsStats.value.failed || 0,
}));

const selectedStatusesLabel = computed(() => {
  if (!filters.statuses.length || filters.statuses.length === TASK_STATUS_OPTIONS.length) {
    return '全部状态';
  }
  if (filters.statuses.length === 1) {
    return TASK_STATUS_OPTIONS.find((item) => item.value === filters.statuses[0])?.label || '已筛选';
  }
  return `已选 ${filters.statuses.length} 项`;
});

const confirmTitle = computed(() => {
  const job = pendingJob.value;
  if (!job) return '立即执行任务';
  if (pendingSyncMode.value === 'full') return `全量同步：${job.name}`;
  if (pendingSyncMode.value === 'incremental') return `增量同步：${job.name}`;
  return `立即执行：${job.name}`;
});

const confirmDescription = computed(() => {
  const job = pendingJob.value;
  if (!job) return '';
  if (pendingSyncMode.value === 'full') {
    return `确认立即执行“${job.name}”全量同步吗？全量同步会覆盖该任务覆盖范围内的全部历史数据，耗时更长、成本更高。任务将在后台运行，执行结果可在执行记录中查看。`;
  }
  if (pendingSyncMode.value === 'incremental') {
    return `确认立即执行“${job.name}”增量同步吗？任务将在后台运行，执行结果可在执行记录中查看。`;
  }
  return `确认立即执行“${job.name}”吗？任务将在后台运行，执行结果可在执行记录中查看。`;
});

function dateStartIso(value: string): string {
  return toUtcIsoString(`${value}T00:00:00`);
}

function dateEndIso(value: string): string {
  return toUtcIsoString(`${value}T23:59:59`);
}

function lastRunTime(job: ScheduledTask): string {
  return formatDateTimeInDisplayTimezone(job.latestRun?.finishedAt || job.latestRun?.startedAt);
}

function runStartTime(run: TaskRun): string {
  return formatDateTimeInDisplayTimezone(run.startedAt || run.createdAt);
}

function buildRunQuery(page = runsPage.value): TaskRunQuery {
  return {
    page,
    pageSize: runsPageSize.value,
    status: filters.statuses.join(',') || undefined,
    taskType: filters.taskType.trim() || undefined,
    keyword: filters.keyword.trim() || undefined,
    startedFrom: filters.startedFrom ? dateStartIso(filters.startedFrom) : undefined,
    startedTo: filters.startedTo ? dateEndIso(filters.startedTo) : undefined,
  };
}

function scheduleKeywordApply() {
  if (keywordTimer) clearTimeout(keywordTimer);
  keywordTimer = setTimeout(() => {
    void loadRuns(1);
  }, 400);
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

function refreshCurrent() {
  if (activeTab.value === 'scheduled') {
    void loadScheduled();
    return;
  }
  void loadRuns(runsPage.value);
}

function resetFilters() {
  filters.statuses = [...DEFAULT_RUN_STATUS_FILTERS];
  filters.taskType = '';
  filters.keyword = '';
  filters.startedFrom = '';
  filters.startedTo = '';
  void loadRuns(1);
}

function requestJobRun(job: ScheduledTask, syncMode: ScheduledSyncMode | null) {
  pendingJob.value = job;
  pendingSyncMode.value = syncMode;
  scheduledDetail.value = null;
}

function closeScheduledDetail() {
  scheduledDetail.value = null;
}

function cancelConfirm() {
  if (runningJobId.value) {
    pendingJob.value = null;
    pendingSyncMode.value = null;
    return;
  }
  const job = pendingJob.value;
  pendingJob.value = null;
  pendingSyncMode.value = null;
  if (job) scheduledDetail.value = job;
}

async function confirmRunScheduled() {
  if (!pendingJob.value) return;
  const job = pendingJob.value;
  const syncMode = pendingSyncMode.value;
  runningJobId.value = job.jobId;
  scheduledError.value = null;
  pendingJob.value = null;
  pendingSyncMode.value = null;
  scheduledDetail.value = null;
  try {
    await tasksApi.runScheduledTask(job.jobId, syncMode ?? undefined);
    const modeLabel =
      syncMode === 'full' ? '全量同步' : syncMode === 'incremental' ? '增量同步' : '';
    toast.success(`${modeLabel ? `${modeLabel}任务` : '任务'}已提交，可在执行记录中查看进度`);
    await loadScheduled();
  } catch (err) {
    scheduledError.value = getParsedApiError(err);
  } finally {
    runningJobId.value = null;
  }
}

async function openRunDetail(item: TaskRun) {
  detailOpen.value = true;
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

function closeRunDetail() {
  detailOpen.value = false;
  detail.value = null;
  detailError.value = null;
}

function toggleStatus(status: TaskStatus, checked: boolean) {
  if (checked) {
    if (!filters.statuses.includes(status)) filters.statuses = [...filters.statuses, status];
  } else if (filters.statuses.length > 1) {
    filters.statuses = filters.statuses.filter((item) => item !== status);
  }
  void loadRuns(1);
}

function dismissPageError() {
  scheduledError.value = null;
  runsError.value = null;
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

onBeforeUnmount(() => {
  if (keywordTimer) clearTimeout(keywordTimer);
});
</script>

<template>
  <div class="space-y-6 py-4 sm:py-6">
    <PageHeader
      title="任务中心"
      :description="isAdmin ? '了解定时任务是否正常运行，并查看最近的执行结果。' : '查看自己的任务执行记录。'"
    >
      <template #actions>
        <LoadingButton
          variant="outline"
          size="sm"
          :loading="activeTab === 'scheduled' ? scheduledLoading : runsLoading"
          @click="refreshCurrent"
        >
          <RefreshCcw class="size-4" />
          刷新
        </LoadingButton>
      </template>
    </PageHeader>

    <ModuleTabs
      :items="navItems"
      :active-key="activeTab"
      label="任务中心导航"
    />
    <Separator />

    <AppApiErrorAlert
      v-if="pageError"
      :error="pageError"
      @dismiss="dismissPageError"
    />

    <section
      v-if="activeTab === 'scheduled' && isAdmin"
      class="min-w-0 space-y-4"
    >
      <Card>
        <CardHeader class="border-b">
          <CardTitle>定时任务</CardTitle>
          <CardDescription>
            由 Celery Beat 按代码中的周期定义调度，Celery Worker 负责执行。
          </CardDescription>
          <CardAction>
            <Badge variant="outline">
              {{ scheduledOverview.total }} 项
            </Badge>
          </CardAction>
        </CardHeader>
        <CardContent class="space-y-4">
          <div
            data-testid="scheduled-overview"
            class="grid gap-3 sm:grid-cols-4"
          >
            <div class="rounded border p-3">
              <p class="text-xs text-muted-foreground">
                定时任务
              </p>
              <strong class="mt-1 block tabular-nums">{{ scheduledOverview.total }}</strong>
            </div>
            <div class="rounded border p-3">
              <p class="text-xs text-muted-foreground">
                正常
              </p>
              <strong class="mt-1 block tabular-nums">{{ scheduledOverview.ok }}</strong>
            </div>
            <div class="rounded border p-3">
              <p class="text-xs text-muted-foreground">
                执行中
              </p>
              <strong class="mt-1 block tabular-nums">{{ scheduledOverview.running }}</strong>
            </div>
            <div class="rounded border p-3">
              <p class="text-xs text-muted-foreground">
                异常 / 不可用
              </p>
              <strong class="mt-1 block tabular-nums">{{ scheduledOverview.issue }}</strong>
            </div>
          </div>

          <div
            v-if="scheduledLoading"
            class="space-y-2"
          >
            <Skeleton
              v-for="index in 4"
              :key="index"
              class="h-12 w-full"
            />
          </div>
          <Empty v-else-if="!scheduledItems.length">
            <EmptyHeader>
              <EmptyTitle>暂无定时任务</EmptyTitle>
              <EmptyDescription>当前没有可展示的周期任务定义。</EmptyDescription>
            </EmptyHeader>
          </Empty>
          <Table
            v-else
            data-testid="scheduled-table"
          >
            <TableHeader>
              <TableRow>
                <TableHead>任务</TableHead>
                <TableHead>调度规则</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>最近执行</TableHead>
                <TableHead>下次执行</TableHead>
                <TableHead class="w-[72px] text-right">
                  详情
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="job in scheduledItems"
                :key="job.jobId"
              >
                <TableCell class="max-w-[280px]">
                  <p class="font-medium">
                    {{ job.name }}
                  </p>
                  <p
                    v-if="job.description"
                    class="mt-0.5 truncate text-xs text-muted-foreground"
                  >
                    {{ job.description }}
                  </p>
                </TableCell>
                <TableCell class="whitespace-nowrap text-muted-foreground">
                  {{ job.schedule }}
                </TableCell>
                <TableCell>
                  <Badge :variant="jobStatusVariant(job)">
                    {{ jobStatusLabel(job) }}
                  </Badge>
                </TableCell>
                <TableCell>
                  <div
                    v-if="job.latestRun"
                    class="flex items-center gap-2"
                  >
                    <Badge :variant="runStatusVariant(job.latestRun.status)">
                      {{ runStatusLabel(job.latestRun.status) }}
                    </Badge>
                    <span class="whitespace-nowrap text-xs text-muted-foreground">
                      {{ lastRunTime(job) }}
                    </span>
                  </div>
                  <span
                    v-else
                    class="text-sm text-muted-foreground"
                  >暂无记录</span>
                </TableCell>
                <TableCell class="whitespace-nowrap text-muted-foreground">
                  {{ formatDateTimeInDisplayTimezone(job.nextRunTime) }}
                </TableCell>
                <TableCell class="text-right">
                  <Button
                    size="sm"
                    variant="ghost"
                    @click="scheduledDetail = job"
                  >
                    详情
                  </Button>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </section>

    <section
      v-else
      class="min-w-0 space-y-4"
    >
      <Card>
        <CardHeader class="border-b">
          <CardTitle>执行记录</CardTitle>
          <CardDescription>
            {{ isAdmin ? '查看全部用户和系统任务的运行结果。' : '查看自己的任务运行结果、耗时和失败原因。' }}
          </CardDescription>
        </CardHeader>
        <CardContent class="space-y-4">
          <div
            data-testid="runs-overview"
            class="grid gap-3 sm:grid-cols-4"
          >
            <div class="rounded border p-3">
              <p class="text-xs text-muted-foreground">
                总记录
              </p>
              <strong class="mt-1 block tabular-nums">{{ runOverview.total }}</strong>
            </div>
            <div class="rounded border p-3">
              <p class="text-xs text-muted-foreground">
                执行中
              </p>
              <strong class="mt-1 block tabular-nums">{{ runOverview.running }}</strong>
            </div>
            <div class="rounded border p-3">
              <p class="text-xs text-muted-foreground">
                成功
              </p>
              <strong class="mt-1 block tabular-nums">{{ runOverview.success }}</strong>
            </div>
            <div class="rounded border p-3">
              <p class="text-xs text-muted-foreground">
                失败
              </p>
              <strong class="mt-1 block tabular-nums">{{ runOverview.failed }}</strong>
            </div>
          </div>

          <div
            data-testid="runs-filter"
            class="flex flex-wrap items-center gap-2"
          >
            <div class="relative min-w-[220px] flex-1">
              <Search class="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                v-model="filters.keyword"
                class="pl-8"
                placeholder="搜索任务名称、消息或任务 ID"
                @keyup.enter="loadRuns(1)"
                @update:model-value="scheduleKeywordApply"
              />
            </div>
            <DropdownMenu>
              <DropdownMenuTrigger as-child>
                <Button
                  variant="outline"
                  size="sm"
                >
                  <SlidersHorizontal class="size-4" />
                  {{ selectedStatusesLabel }}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="start"
                class="w-48"
              >
                <DropdownMenuLabel>状态</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuCheckboxItem
                  v-for="item in TASK_STATUS_OPTIONS"
                  :key="item.value"
                  :model-value="filters.statuses.includes(item.value)"
                  @update:model-value="(checked) => toggleStatus(item.value, Boolean(checked))"
                  @select.prevent
                >
                  {{ item.label }}
                </DropdownMenuCheckboxItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Input
              v-model="filters.taskType"
              class="w-[180px]"
              placeholder="任务类型"
              @keyup.enter="loadRuns(1)"
              @blur="loadRuns(1)"
            />
            <AppDatePicker
              v-model="filters.startedFrom"
              class="w-[168px]"
              placeholder="开始日期"
              @update:model-value="loadRuns(1)"
            />
            <AppDatePicker
              v-model="filters.startedTo"
              class="w-[168px]"
              placeholder="结束日期"
              @update:model-value="loadRuns(1)"
            />
            <Button
              variant="ghost"
              size="sm"
              @click="resetFilters"
            >
              重置
            </Button>
          </div>

          <div
            v-if="runsLoading"
            class="space-y-2"
          >
            <Skeleton
              v-for="index in 5"
              :key="index"
              class="h-12 w-full"
            />
          </div>
          <Empty v-else-if="!runs.length">
            <EmptyHeader>
              <EmptyTitle>暂无执行记录</EmptyTitle>
              <EmptyDescription>调整筛选条件后再试，或等待任务执行完成。</EmptyDescription>
            </EmptyHeader>
          </Empty>
          <template v-else>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>任务</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>开始时间</TableHead>
                  <TableHead>耗时</TableHead>
                  <TableHead>结果摘要</TableHead>
                  <TableHead class="w-[72px] text-right">
                    详情
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow
                  v-for="run in runs"
                  :key="run.taskId"
                >
                  <TableCell class="max-w-[240px]">
                    <p class="font-medium">
                      {{ run.taskName || run.taskType }}
                    </p>
                  </TableCell>
                  <TableCell>
                    <Badge :variant="runStatusVariant(run.status)">
                      {{ runStatusLabel(run.status) }}
                    </Badge>
                  </TableCell>
                  <TableCell class="whitespace-nowrap text-muted-foreground">
                    {{ runStartTime(run) }}
                  </TableCell>
                  <TableCell class="whitespace-nowrap text-muted-foreground">
                    {{ formatDuration(run.durationSeconds) }}
                  </TableCell>
                  <TableCell class="max-w-[320px] text-muted-foreground">
                    {{ truncateText(run.message, 72) || '—' }}
                  </TableCell>
                  <TableCell class="text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      :disabled="detailLoading"
                      @click="openRunDetail(run)"
                    >
                      详情
                    </Button>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
            <AppPagination
              :current-page="runsPage"
              :total-pages="totalPages"
              class="pt-2"
              @page-change="loadRuns"
            />
          </template>
        </CardContent>
      </Card>
    </section>

    <ScheduledTaskDetailDialog
      :job="scheduledDetail"
      :running="runningJobId !== null"
      @update:open="(open) => { if (!open) closeScheduledDetail() }"
      @run="requestJobRun"
    />
    <TaskRunDetailDialog
      :open="detailOpen"
      :detail="detail"
      :loading="detailLoading"
      :error="detailError"
      :is-admin="isAdmin"
      @update:open="(open) => { if (!open) closeRunDetail() }"
      @dismiss-error="detailError = null"
    />
    <AppConfirmDialog
      :open="!!pendingJob"
      :title="confirmTitle"
      :description="confirmDescription"
      confirm-text="立即执行"
      :destructive="pendingSyncMode === 'full'"
      @confirm="confirmRunScheduled"
      @update:open="(open) => { if (!open) cancelConfirm() }"
    />
  </div>
</template>
