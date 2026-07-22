import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { quantApi } from '@/api/quant';
import { useAuthStore } from '@/stores/authStore';
import type { QuantDatasetSnapshot } from '@/types/quant';
import QuantDatasetsPage from '../quant/QuantDatasetsPage.vue';

vi.mock('@/api/quant', () => ({
  quantApi: {
    datasets: vi.fn(),
    buildDataset: vi.fn(),
    modelDefinitions: vi.fn(),
    createModelRun: vi.fn(),
  },
}));

const snapshots: QuantDatasetSnapshot[] = [
  {
    id: 8,
    datasetKey: 'cn-ready',
    market: 'CN',
    dateFrom: '2021-01-01',
    dateTo: '2026-07-22',
    priceMode: 'forward_adjusted',
    featureVersion: 'feature-v1',
    artifactUri: 'quant://datasets/cn-ready',
    rowCount: 620000,
    symbolCount: 300,
    status: 'ready',
    validationResult: { valid: true },
    createdAt: '2026-07-22T06:30:00Z',
    finishedAt: '2026-07-22T06:31:00Z',
  },
  {
    id: 9,
    datasetKey: 'cn-building',
    market: 'CN',
    dateFrom: '2021-01-01',
    dateTo: '2026-07-22',
    priceMode: 'raw',
    featureVersion: 'feature-v1',
    artifactUri: null,
    rowCount: 0,
    symbolCount: 0,
    status: 'building',
    validationResult: {},
    createdAt: '2026-07-22T07:00:00Z',
    finishedAt: null,
  },
];

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
      { path: '/market/quant/datasets', component: QuantDatasetsPage },
      { path: '/market/quant/models', component: { template: '<div>models</div>' } },
      { path: '/tasks/runs', component: { template: '<div>tasks</div>' } },
    ],
  });
  await router.push('/market/quant/datasets?market=CN');
  await router.isReady();
  const wrapper = mount(QuantDatasetsPage, {
    global: {
      plugins: [pinia, router],
      stubs: { Teleport: true },
    },
  });
  await flushPromises();
  return { wrapper, router };
}

describe('QuantDatasetsPage', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 6, 22, 15, 30));
    vi.clearAllMocks();
    vi.mocked(quantApi.datasets).mockResolvedValue(snapshots);
    vi.mocked(quantApi.modelDefinitions).mockResolvedValue([
      {
        id: 1,
        key: 'cross_section_lgbm',
        name: 'Qlib Alpha158 LightGBM',
        modelType: 'cross_section',
        taskType: 'regression',
        frequency: 'day',
        enabled: true,
        supportedMarkets: ['CN'],
      },
    ]);
    vi.mocked(quantApi.buildDataset).mockResolvedValue({
      taskId: 'dataset-task',
      status: 'pending',
      market: 'CN',
      universe: 'cn_csi300',
    });
    vi.mocked(quantApi.createModelRun).mockResolvedValue({
      modelRunId: 19,
      taskId: 'training-task',
      status: 'pending',
      market: 'CN',
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('opens a centered build dialog with the default five-year range and no drawer animation', async () => {
    const { wrapper } = await mountPage();

    await wrapper.get('[data-testid="open-dataset-build"]').trigger('click');

    expect(wrapper.get('[role="dialog"]').text()).toContain('构建数据集');
    expect(wrapper.get('[data-testid="dialog-panel"]').classes()).toContain('max-w-2xl');
    expect(wrapper.get('[data-testid="dataset-date-from"]').element).toHaveProperty('value', '2021-07-22');
    expect(wrapper.get('[data-testid="dataset-date-to"]').element).toHaveProperty('value', '2026-07-22');
    expect(wrapper.get('[data-testid="dataset-universe"]').element).toHaveProperty('value', '沪深300 / cn_csi300');
    expect(wrapper.html()).not.toContain('animate-slide-in-right');
    expect(wrapper.html()).not.toContain('quant-training-drawer');
  });

  it('does not submit an invalid date range', async () => {
    const { wrapper } = await mountPage();
    await wrapper.get('[data-testid="open-dataset-build"]').trigger('click');
    await wrapper.get('[data-testid="dataset-date-from"]').setValue('2026-07-23');
    await wrapper.get('[data-testid="dataset-date-to"]').setValue('2026-07-22');

    expect(wrapper.get('[data-testid="submit-dataset-build"]').attributes('disabled')).toBeDefined();
    await wrapper.get('[data-testid="dataset-build-form"]').trigger('submit');

    expect(quantApi.buildDataset).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('日期范围无效');
  });

  it('submits the selected market payload, closes, reports the task, and refreshes datasets', async () => {
    const { wrapper } = await mountPage();
    await wrapper.get('[data-testid="open-dataset-build"]').trigger('click');
    await wrapper.get('input[type="radio"][value="CN"]').setValue();
    await wrapper.get('[data-testid="dataset-date-from"]').setValue('2021-01-01');
    await wrapper.get('[data-testid="dataset-date-to"]').setValue('2026-07-22');
    await wrapper.get('[data-testid="dataset-build-form"]').trigger('submit');
    await flushPromises();

    expect(quantApi.buildDataset).toHaveBeenCalledWith('CN', '2021-01-01', '2026-07-22');
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    expect(wrapper.text()).toContain('数据集构建任务已提交');
    expect(wrapper.text()).toContain('dataset-task');
    expect(quantApi.datasets).toHaveBeenCalledTimes(2);
  });

  it('preselects a ready row in the training dialog and never enables non-ready rows', async () => {
    const { wrapper } = await mountPage();

    expect(wrapper.find('[data-testid="train-with-dataset-9"]').exists()).toBe(false);
    await wrapper.get('[data-testid="train-with-dataset-8"]').trigger('click');
    await flushPromises();

    const selected = wrapper.get('input[type="radio"][value="8"]');
    expect((selected.element as HTMLInputElement).checked).toBe(true);
    expect(wrapper.get('[role="dialog"]').text()).toContain('由所选数据集确定');
    expect(wrapper.find('[data-testid="dataset-date-from"]').exists()).toBe(false);
  });
});
