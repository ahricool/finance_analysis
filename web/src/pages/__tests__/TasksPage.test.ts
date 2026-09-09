import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { tasksApi } from '@/api/tasks';
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

const runsResponse: TaskRunsResponse = {
  items: [sampleRun],
  total: 1,
  page: 1,
  pageSize: 10,
  statistics: {
    pending: 0,
    processing: 1,
    completed: 5,
    failed: 2,
    skipped: 0,
    retrying: 0,
    cancelled: 0,
  },
};

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

describe('TasksPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(tasksApi.getScheduledTasks).mockResolvedValue({ items: [cnDailySync] });
    vi.mocked(tasksApi.getTaskRuns).mockResolvedValue(runsResponse);
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

  it('does not mention APScheduler and keeps technical ids out of the scheduled table', async () => {
    const wrapper = await mountPage();

    expect(wrapper.text()).not.toContain('APScheduler');
    expect(wrapper.text()).toContain('Celery Beat');
    expect(wrapper.get('[data-testid="scheduled-overview"]').text()).toContain('定时任务');

    const tableText = wrapper.get('[data-testid="scheduled-table"]').text();
    expect(tableText).toContain('A股日线行情同步');
    expect(tableText).toContain('周一至周五 18:00');
    expect(tableText).not.toContain('market_data_sync_cn_hk');
    expect(tableText).not.toContain('scheduled_market_data_sync_cn_hk');
    expect(tableText).not.toContain('立即执行');
    expect(tableText).not.toContain('全量同步');
    expect(tableText).not.toContain('增量同步');

    wrapper.unmount();
  });

  it('submits a full CN daily sync from the scheduled task detail dialog', async () => {
    const wrapper = await mountPage();
    const detailButton = wrapper
      .get('[data-testid="scheduled-table"]')
      .findAll('button')
      .find((button) => button.text().trim() === '详情');

    expect(detailButton).toBeDefined();
    await detailButton?.trigger('click');
    await flushPromises();

    const detailDialog = document.body.querySelector('[data-testid="scheduled-task-detail"]');
    expect(detailDialog).not.toBeNull();
    expect(detailDialog?.textContent).toContain('market_data_sync_cn_hk');

    const fullSync = Array.from(detailDialog?.querySelectorAll('button') ?? []).find(
      (button) => button.textContent?.trim() === '全量同步',
    );
    expect(fullSync).toBeDefined();
    fullSync?.click();
    await flushPromises();

    const dialog = document.body.querySelector('[role="alertdialog"]');
    expect(dialog).not.toBeNull();
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

  it('hides uid/source/trigger filters on the runs page and keeps technical fields in the detail dialog', async () => {
    const wrapper = await mountPage('/tasks/runs');

    expect(wrapper.text()).not.toContain('APScheduler');
    expect(textOf('[data-testid="runs-filter"]')).not.toContain('UID');
    expect(textOf('[data-testid="runs-filter"]')).not.toContain('全部来源');
    expect(textOf('[data-testid="runs-filter"]')).not.toContain('全部触发');
    expect(wrapper.text()).not.toContain('triggerSource');

    const query = vi.mocked(tasksApi.getTaskRuns).mock.calls.at(-1)?.[0];
    expect(query).toEqual(
      expect.not.objectContaining({
        uid: expect.anything(),
        source: expect.anything(),
        triggerSource: expect.anything(),
      }),
    );
    expect(query).not.toHaveProperty('uid');
    expect(query).not.toHaveProperty('source');
    expect(query).not.toHaveProperty('triggerSource');

    const tableText = wrapper.get('table').text();
    expect(tableText).toContain('A股日线行情同步');
    expect(tableText).toContain('成功');
    expect(tableText).not.toContain('task-run-1');
    expect(tableText).not.toContain('admin@example.com');
    expect(tableText).not.toContain('定时触发');

    const detailButton = wrapper.findAll('button').find((button) => button.text().trim() === '详情');
    await detailButton?.trigger('click');
    await flushPromises();

    const detailDialog = document.body.querySelector('[data-testid="task-run-detail"]');
    expect(detailDialog?.textContent).toContain('task-run-1');
    expect(detailDialog?.textContent).toContain('Payload');
    expect(detailDialog?.textContent).toContain('定时任务');

    wrapper.unmount();
  });
});
