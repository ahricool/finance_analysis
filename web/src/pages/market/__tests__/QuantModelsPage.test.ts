import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { quantApi } from '@/api/quant';
import { useAuthStore } from '@/stores/authStore';
import QuantModelsPage from '../quant/QuantModelsPage.vue';

vi.mock('@/api/quant', () => ({
  quantApi: {
    models: vi.fn(),
    modelDefinitions: vi.fn(),
    datasets: vi.fn(),
    buildDataset: vi.fn(),
    createModelRun: vi.fn(),
  },
}));

async function mountPage(role: 'admin' | 'user') {
  const pinia = createPinia();
  const auth = useAuthStore(pinia);
  auth.currentUser = {
    id: 1,
    uid: 1,
    username: 'tester',
    email: 'tester@example.com',
    role,
  } as never;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/market/quant/models', component: QuantModelsPage },
      { path: '/market/quant/models/:runId', component: { template: '<div>run detail</div>' } },
      { path: '/tasks/runs', component: { template: '<div>task runs</div>' } },
    ],
  });
  await router.push('/market/quant/models?market=CN');
  await router.isReady();
  const wrapper = mount(QuantModelsPage, {
    global: {
      plugins: [pinia, router],
      stubs: { Teleport: true },
    },
  });
  await flushPromises();
  return { wrapper, router };
}

describe('QuantModelsPage training entry', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(quantApi.models).mockResolvedValue([]);
    vi.mocked(quantApi.modelDefinitions).mockResolvedValue([
      {
        id: 1,
        key: 'cross_section_lgbm',
        name: 'Qlib Alpha158 LightGBM',
        modelType: 'cross_section',
        taskType: 'regression',
        frequency: 'day',
        enabled: true,
        supportedMarkets: ['US', 'CN'],
      },
      {
        id: 2,
        key: 'time_series_lgbm',
        name: 'Shared panel LightGBM',
        modelType: 'time_series',
        taskType: 'regression',
        frequency: 'day',
        enabled: true,
        supportedMarkets: ['US', 'CN'],
      },
    ]);
    vi.mocked(quantApi.datasets).mockResolvedValue([
      {
        id: 8,
        datasetKey: 'cn-ready',
        market: 'CN',
        dateFrom: '2021-01-01',
        dateTo: '2026-07-20',
        priceMode: 'raw',
        featureVersion: 'v1',
        artifactUri: 'quant://datasets/cn-ready',
        rowCount: 1000,
        symbolCount: 300,
        status: 'ready',
        validationResult: {},
        createdAt: '2026-07-21T00:00:00Z',
        finishedAt: '2026-07-21T00:01:00Z',
      },
    ]);
    vi.mocked(quantApi.createModelRun).mockResolvedValue({
      modelRunId: 19,
      taskId: 'training-task',
      status: 'draft',
      market: 'CN',
    });
    vi.mocked(quantApi.buildDataset).mockResolvedValue({
      taskId: 'dataset-task',
      status: 'pending',
      market: 'CN',
      universe: 'cn_csi300',
    });
  });

  it('shows the entry only to administrators', async () => {
    const { wrapper: userPage } = await mountPage('user');
    expect(userPage.find('[data-testid="open-quant-training"]').exists()).toBe(false);
    userPage.unmount();

    const { wrapper: adminPage } = await mountPage('admin');
    expect(adminPage.get('[data-testid="open-quant-training"]').text()).toContain('创建训练任务');
  });

  it('creates a market-scoped training run from a ready dataset', async () => {
    const { wrapper, router } = await mountPage('admin');

    await wrapper.get('[data-testid="open-quant-training"]').trigger('click');
    await flushPromises();
    expect(quantApi.modelDefinitions).toHaveBeenCalledWith('CN');
    expect(quantApi.datasets).toHaveBeenCalledWith('CN');

    await wrapper.get('[data-testid="training-model-select"]').setValue('time_series_lgbm');
    await wrapper.get('[data-testid="training-model-version"]').setValue('cn-time-series-v1');
    expect(wrapper.get('[data-testid="create-training-run"]').attributes('disabled')).toBeUndefined();
    await wrapper.get('[data-testid="training-run-form"]').trigger('submit');
    await flushPromises();

    expect(quantApi.createModelRun).toHaveBeenCalledWith({
      market: 'CN',
      modelKey: 'time_series_lgbm',
      modelVersion: 'cn-time-series-v1',
      datasetSnapshotId: 8,
    });
    expect(router.currentRoute.value.path).toBe('/market/quant/models/19');
    expect(router.currentRoute.value.query.market).toBe('CN');
  });

  it('submits a market-scoped dataset build prerequisite', async () => {
    const { wrapper } = await mountPage('admin');

    await wrapper.get('[data-testid="open-quant-training"]').trigger('click');
    await flushPromises();
    await wrapper.get('[data-testid="dataset-date-from"]').setValue('2021-01-01');
    await wrapper.get('[data-testid="dataset-date-to"]').setValue('2026-07-20');
    await wrapper.get('[data-testid="dataset-build-form"]').trigger('submit');
    await flushPromises();

    expect(quantApi.buildDataset).toHaveBeenCalledWith('CN', '2021-01-01', '2026-07-20');
    expect(wrapper.text()).toContain('数据集构建任务已提交');
    expect(wrapper.text()).toContain('dataset-task');
  });
});
