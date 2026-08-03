import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { tasksApi } from '@/api/tasks';
import { useAuthStore } from '@/stores/authStore';
import type { ScheduledTask } from '@/types/tasks';
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

async function mountPage() {
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
      { path: '/tasks/scheduled', component: TasksPage },
      { path: '/tasks/runs', component: { template: '<div>runs</div>' } },
    ],
  });
  await router.push('/tasks/scheduled');
  await router.isReady();
  const wrapper = mount(TasksPage, {
    attachTo: document.body,
    global: { plugins: [pinia, router] },
  });
  await flushPromises();
  return wrapper;
}

describe('TasksPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(tasksApi.getScheduledTasks).mockResolvedValue({ items: [cnDailySync] });
    vi.mocked(tasksApi.runScheduledTask).mockResolvedValue({
      taskId: 'task-full-cn',
      jobId: cnDailySync.jobId,
      status: 'pending',
      message: 'submitted',
      syncMode: 'full',
    });
  });

  it('submits a full CN daily sync from the scheduled tasks table', async () => {
    const wrapper = await mountPage();
    const fullSync = wrapper
      .get('table')
      .findAll('button')
      .find((button) => button.text().trim() === '全量同步');

    expect(fullSync).toBeDefined();
    await fullSync?.trigger('click');
    await flushPromises();

    const dialog = document.body.querySelector('[role="alertdialog"]');
    expect(dialog).not.toBeNull();
    const confirm = Array.from(dialog?.querySelectorAll('button') ?? []).find(
      (button) => button.textContent?.trim() === '立即执行',
    );
    expect(confirm).toBeDefined();
    confirm?.click();
    await flushPromises();

    expect(tasksApi.runScheduledTask).toHaveBeenCalledWith(cnDailySync.jobId, 'full');
    wrapper.unmount();
  });
});
