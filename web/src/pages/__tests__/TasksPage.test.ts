import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { tasksApi, type TaskRunQuery } from '@/api/tasks';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import { useAuthStore } from '@/stores/authStore';
import type { ScheduledTask, TaskRun, TaskRunsResponse } from '@/types/tasks';
import TasksPage from '../TasksPage.vue';

vi.mock('@/api/tasks', () => ({
  tasksApi: {
    getScheduledTasks: vi.fn(),
    runScheduledTask: vi.fn(),
    getTaskRuns: vi.fn(),
    getTaskRunDetail: vi.fn(),
  },
}));

const cnDailySync: ScheduledTask = {
  jobId: 'market_data_sync_cn_hk',
  name: 'A股日线行情同步',
  description: '同步A股日线行情',
  taskType: 'scheduled_market_data_sync_cn_hk',
  schedule: '周一至周五 18:00',
  timezone: 'Asia/Shanghai',
  schedulerStatus: 'active',
  nextRunTime: '2026-08-03T10:00:00Z',
  allowManualRun: true,
  syncModes: ['incremental', 'full'],
  latestRun: null,
};

const sampleRun: TaskRun = {
  id: 1,
  taskId: 'task-run-1',
  taskName: 'A股日线行情同步',
  taskType: 'scheduled_market_data_sync_cn_hk',
  uid: 1,
  user: { uid: 1, username: 'admin', email: 'admin@example.com', role: 'admin' },
  source: 'celery',
  triggerSource: 'scheduler',
  triggeredByUid: null,
  status: 'completed',
  progress: 100,
  message: '同步完成，共写入 120 条日线',
  schedulerJobId: 'market_data_sync_cn_hk',
  parentTaskId: null,
  retryCount: 0,
  createdAt: '2026-08-03T10:00:00Z',
  startedAt: '2026-08-03T10:00:01Z',
  finishedAt: '2026-08-03T10:01:00Z',
  updatedAt: '2026-08-03T10:01:00Z',
  durationSeconds: 59,
};

const listResponse: TaskRunsResponse = {
  items: [sampleRun],
  total: 1,
  page: 1,
  pageSize: 20,
  statistics: {
    pending: 0,
    processing: 0,
    completed: 1,
    failed: 0,
    skipped: 0,
    retrying: 0,
    cancelled: 0,
  },
};

const overviewResponse: TaskRunsResponse = {
  items: [],
  total: 109,
  page: 1,
  pageSize: 1,
  statistics: {
    pending: 1,
    processing: 3,
    retrying: 1,
    completed: 100,
    failed: 2,
    skipped: 1,
    cancelled: 1,
  },
};

function isOverviewQuery(query?: TaskRunQuery) {
  if (!query) return false;
  return (
    query.page === 1
    && query.pageSize === 1
    && query.status === undefined
    && query.taskType === undefined
    && query.keyword === undefined
    && query.startedFrom === undefined
    && query.startedTo === undefined
    && query.source === undefined
    && query.triggerSource === undefined
    && query.uid === undefined
  );
}

function overviewQueries() {
  return vi.mocked(tasksApi.getTaskRuns).mock.calls.map(([query]) => query).filter(isOverviewQuery);
}

function listQueries() {
  return vi.mocked(tasksApi.getTaskRuns).mock.calls.map(([query]) => query).filter((query) => !isOverviewQuery(query));
}

function expectOverview(wrapper: Awaited<ReturnType<typeof mountPage>>) {
  const text = wrapper.get('[data-testid="runs-overview"]').text().replace(/\s+/g, '');
  expect(text).toContain('总记录109');
  expect(text).toContain('执行中5');
  expect(text).toContain('成功100');
  expect(text).toContain('失败2');
}

function expectNoBusinessFilters(query?: TaskRunQuery) {
  expect(query).toEqual({ page: 1, pageSize: 1 });
  expect(query).not.toHaveProperty('status');
  expect(query).not.toHaveProperty('taskType');
  expect(query).not.toHaveProperty('keyword');
  expect(query).not.toHaveProperty('startedFrom');
  expect(query).not.toHaveProperty('startedTo');
  expect(query).not.toHaveProperty('source');
  expect(query).not.toHaveProperty('triggerSource');
  expect(query).not.toHaveProperty('uid');
}

async function mountPage(path = '/tasks/scheduled') {
  const pinia = createPinia();
  const auth = useAuthStore(pinia);
  auth.currentUser = {
    id: 1,
    uid: 1,
    username: 'admin',
    email: 'admin@example.com',
    role: 'admin',
  } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/tasks', name: 'tasks', component: TasksPage },
      { path: '/tasks/scheduled', name: 'tasks-scheduled', component: TasksPage },
      { path: '/tasks/runs', name: 'tasks-runs', component: TasksPage },
    ],
  });
  await router.push(path);
  await router.isReady();
  const wrapper = mount(TasksPage, {
    attachTo: document.body,
    global: { plugins: [pinia, router] },
  });
  await flushPromises();
  return wrapper;
}

function textOf(selector: string) {
  return document.body.querySelector(selector)?.textContent ?? '';
}

async function openFirstScheduledDetail(wrapper: Awaited<ReturnType<typeof mountPage>>) {
  const row = wrapper.get('[data-testid="scheduled-table"]').findAll('tbody tr')[0];
  expect(row).toBeDefined();
  await row?.trigger('click');
  await flushPromises();
  return document.body.querySelector('[data-testid="scheduled-task-detail"]');
}

function dialogButtonLabels(dialog: Element | null) {
  return Array.from(dialog?.querySelectorAll('button') ?? []).map((button) => button.textContent?.trim());
}

describe('TasksPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(tasksApi.getScheduledTasks).mockResolvedValue({ items: [cnDailySync] });
    vi.mocked(tasksApi.getTaskRuns).mockImplementation(async (query) => {
      if (isOverviewQuery(query)) return overviewResponse;
      return listResponse;
    });
    vi.mocked(tasksApi.getTaskRunDetail).mockResolvedValue({
      ...sampleRun,
      payload: { syncMode: 'incremental' },
      result: { written: 120 },
      error: null,
      taskLog: 'ok',
    });
    vi.mocked(tasksApi.runScheduledTask).mockResolvedValue({
      taskId: 'task-full-cn',
      jobId: cnDailySync.jobId,
      status: 'pending',
      message: 'submitted',
      syncMode: 'full',
    });
  });

  it('does not mention APScheduler and shows job ids in the scheduled table', async () => {
    const wrapper = await mountPage();

    expect(wrapper.text()).not.toContain('APScheduler');
    expect(wrapper.text()).toContain('Celery Beat');
    expect(wrapper.get('[data-testid="scheduled-overview"]').text()).toContain('定时任务');

    const tableText = wrapper.get('[data-testid="scheduled-table"]').text();
    expect(tableText).toContain('A股日线行情同步');
    expect(tableText).toContain('周一至周五 18:00');
    expect(tableText).toContain('market_data_sync_cn_hk');
    expect(tableText).not.toContain('同步A股日线行情');
    expect(tableText).not.toContain('scheduled_market_data_sync_cn_hk');
    expect(tableText).not.toContain('立即执行');
    expect(tableText).not.toContain('全量同步');
    expect(tableText).not.toContain('增量同步');
    expect(tableText).not.toContain('详情');

    wrapper.unmount();
  });

  it('submits a full CN daily sync from the scheduled task detail dialog', async () => {
    const wrapper = await mountPage();
    const detailDialog = await openFirstScheduledDetail(wrapper);
    expect(detailDialog).not.toBeNull();
    expect(detailDialog?.textContent).toContain('market_data_sync_cn_hk');
    expect(dialogButtonLabels(detailDialog)).toEqual(expect.arrayContaining(['增量同步', '全量同步']));

    const fullSync = Array.from(detailDialog?.querySelectorAll('button') ?? []).find(
      (button) => button.textContent?.trim() === '全量同步',
    );
    fullSync?.click();
    await flushPromises();

    const dialog = document.body.querySelector('[role="alertdialog"]');
    expect(dialog).not.toBeNull();
    expect(document.body.querySelector('[data-testid="scheduled-task-detail"]')).toBeNull();
    expect(dialog?.textContent).toContain('全量同步会覆盖');
    const confirm = Array.from(dialog?.querySelectorAll('button') ?? []).find(
      (button) => button.textContent?.trim() === '立即执行',
    );
    expect(confirm).toBeDefined();
    confirm?.click();
    await flushPromises();

    expect(tasksApi.runScheduledTask).toHaveBeenCalledWith(cnDailySync.jobId, 'full');
    wrapper.unmount();
  });

  it.each([
    { syncModes: ['incremental'] as const, visible: ['增量同步'], hidden: ['全量同步'] },
    { syncModes: ['full'] as const, visible: ['全量同步'], hidden: ['增量同步'] },
    { syncModes: ['incremental', 'full'] as const, visible: ['增量同步', '全量同步'], hidden: [] },
  ])('shows sync buttons matching $syncModes', async ({ syncModes, visible, hidden }) => {
    vi.mocked(tasksApi.getScheduledTasks).mockResolvedValue({
      items: [{ ...cnDailySync, syncModes: [...syncModes] }],
    });
    const wrapper = await mountPage();
    const detailDialog = await openFirstScheduledDetail(wrapper);
    const labels = dialogButtonLabels(detailDialog);
    for (const label of visible) expect(labels).toContain(label);
    for (const label of hidden) expect(labels).not.toContain(label);
    expect(labels).not.toContain('立即执行');
    wrapper.unmount();
  });

  it('hides uid/source/trigger filters on the runs page and keeps technical fields in the detail dialog', async () => {
    const wrapper = await mountPage('/tasks/runs');

    expect(wrapper.text()).not.toContain('APScheduler');
    expect(textOf('[data-testid="runs-filter"]')).not.toContain('UID');
    expect(textOf('[data-testid="runs-filter"]')).not.toContain('全部来源');
    expect(textOf('[data-testid="runs-filter"]')).not.toContain('全部触发');
    expect(wrapper.text()).not.toContain('triggerSource');

    for (const query of listQueries()) {
      expect(query).not.toHaveProperty('uid');
      expect(query).not.toHaveProperty('source');
      expect(query).not.toHaveProperty('triggerSource');
    }

    const tableText = wrapper.get('table').text();
    expect(tableText).toContain('A股日线行情同步');
    expect(tableText).toContain('成功');
    expect(tableText).not.toContain('task-run-1');
    expect(tableText).not.toContain('admin@example.com');
    expect(tableText).not.toContain('定时触发');

    const row = wrapper.get('table').findAll('tbody tr')[0];
    await row.trigger('click');
    await flushPromises();

    const detailDialog = document.body.querySelector('[data-testid="task-run-detail"]');
    expect(detailDialog?.textContent).toContain('task-run-1');
    expect(detailDialog?.textContent).toContain('Payload');
    expect(detailDialog?.textContent).toContain('定时任务');

    wrapper.unmount();
  });

  it('loads unfiltered overview stats separately from the filtered table query', async () => {
    const wrapper = await mountPage('/tasks/runs');

    expect(overviewQueries().length).toBeGreaterThanOrEqual(1);
    expectNoBusinessFilters(overviewQueries()[0]);
    expectOverview(wrapper);

    const initialList = listQueries();
    expect(initialList.length).toBeGreaterThanOrEqual(1);
    expect(initialList[0]?.status).toBeTruthy();
    expect(initialList[0]?.pageSize).toBe(20);

    wrapper.unmount();
  });

  it('keeps overview counts unchanged when table filters change', async () => {
    const wrapper = await mountPage('/tasks/runs');
    const overviewCallsBeforeFilters = overviewQueries().length;
    expectOverview(wrapper);

    const keyword = wrapper.get('[data-testid="runs-filter"]').get('input[placeholder="搜索任务名称、消息或任务 ID"]');
    await keyword.setValue('market_data');
    await keyword.trigger('keyup.enter');
    await flushPromises();
    expectOverview(wrapper);

    const taskType = wrapper.get('[data-testid="runs-filter"]').get('input[placeholder="任务类型"]');
    await taskType.setValue('scheduled_market_data_sync_cn_hk');
    await taskType.trigger('blur');
    await flushPromises();
    expectOverview(wrapper);

    const statusTrigger = wrapper
      .get('[data-testid="runs-filter"]')
      .findAll('button')
      .find((button) => button.text().includes('已选') || button.text().includes('全部状态'));
    await statusTrigger?.trigger('click');
    await flushPromises();
    const failedOption = Array.from(document.body.querySelectorAll('[role="menuitemcheckbox"]')).find(
      (item) => item.textContent?.trim() === '失败',
    );
    failedOption?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await flushPromises();
    expectOverview(wrapper);

    const startedPicker = wrapper.findAllComponents(AppDatePicker)[0];
    startedPicker.vm.$emit('update:modelValue', '2026-08-01');
    await flushPromises();
    expectOverview(wrapper);

    expect(overviewQueries()).toHaveLength(overviewCallsBeforeFilters);

    const filtered = listQueries();
    expect(filtered.some((query) => query?.keyword === 'market_data')).toBe(true);
    expect(filtered.some((query) => query?.taskType === 'scheduled_market_data_sync_cn_hk')).toBe(true);
    expect(filtered.some((query) => query?.startedFrom)).toBe(true);

    wrapper.unmount();
  });

  it('ignores stale filtered run responses', async () => {
    const wrapper = await mountPage('/tasks/runs');
    type Deferred = {
      promise: Promise<TaskRunsResponse>;
      resolve: (value: TaskRunsResponse) => void;
    };
    const deferred = (): Deferred => {
      let resolve!: (value: TaskRunsResponse) => void;
      const promise = new Promise<TaskRunsResponse>((next) => {
        resolve = next;
      });
      return { promise, resolve };
    };
    const first = deferred();
    const second = deferred();
    const queue = [first, second];

    vi.mocked(tasksApi.getTaskRuns).mockImplementation(async (query) => {
      if (isOverviewQuery(query)) return overviewResponse;
      const next = queue.shift();
      if (!next) return listResponse;
      return next.promise;
    });

    const keyword = wrapper.get('[data-testid="runs-filter"]').get('input[placeholder="搜索任务名称、消息或任务 ID"]');
    await keyword.setValue('market');
    await keyword.trigger('keyup.enter');
    await keyword.setValue('market_data');
    await keyword.trigger('keyup.enter');

    second.resolve({
      ...listResponse,
      items: [{ ...sampleRun, taskId: 'new-run', taskName: '新请求结果' }],
    });
    await flushPromises();
    first.resolve({
      ...listResponse,
      items: [{ ...sampleRun, taskId: 'old-run', taskName: '旧请求结果' }],
    });
    await flushPromises();

    expect(wrapper.get('table').text()).toContain('新请求结果');
    expect(wrapper.get('table').text()).not.toContain('旧请求结果');
    expectOverview(wrapper);
    wrapper.unmount();
  });
});
