import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { quantApi } from '@/api/quant';
import { useAuthStore } from '@/stores/authStore';
import type { ModelRun, QuantDatasetSnapshot } from '@/types/quant';
import QuantModelsPage from '../quant/QuantModelsPage.vue';

vi.mock('@/api/quant', () => ({
  quantApi: {
    models: vi.fn(),
    deleteModelRun: vi.fn(),
    modelDefinitions: vi.fn(),
    datasets: vi.fn(),
    createModelRun: vi.fn(),
  },
}));

vi.mock('@/components/app/AppConfirmDialog.vue', () => ({
  default: {
    props: ['open', 'title', 'description'],
    emits: ['update:open', 'confirm'],
    template:
      '<div v-if="open" role="alertdialog"><h2>{{ title }}</h2><p>{{ description }}</p><button data-testid="confirm-delete" @click="$emit(\'confirm\'); $emit(\'update:open\', false)">确认删除</button></div>',
  },
}));

vi.mock('@/components/ui/dialog', () => ({
  Dialog: {
    inheritAttrs: false,
    props: ['open'],
    emits: ['update:open'],
    template: '<div v-if="open" role="dialog"><slot /></div>',
  },
  DialogContent: { template: '<div><slot /></div>' },
  DialogScrollContent: { template: '<div><slot /></div>' },
  DialogHeader: { template: '<header><slot /></header>' },
  DialogTitle: { template: '<h2><slot /></h2>' },
  DialogDescription: { template: '<p><slot /></p>' },
  DialogFooter: { template: '<footer><slot /></footer>' },
}));

vi.mock('@/components/forms/FieldSelect.vue', () => ({
  default: {
    inheritAttrs: false,
    props: ['modelValue', 'options', 'label'],
    emits: ['update:modelValue'],
    template: '<label>{{ label }}<select v-bind="$attrs" :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><option v-for="item in options" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>',
  },
}));

const readyDataset: QuantDatasetSnapshot = {
  id: 8,
  datasetKey: 'cn-ready',
  market: 'CN',
  dateFrom: '2021-01-01',
  dateTo: '2026-07-22',
  featureVersion: 'feature-v1',
  artifactUri: 'quant://datasets/cn-ready',
  rowCount: 620000,
  symbolCount: 300,
  universeMemberCount: 302,
  universeCoverageRatio: 300 / 302,
  minimumUniverseCoverage: 0.9,
  trainable: true,
  status: 'ready',
  validationResult: { valid: true },
  createdAt: '2026-07-22T06:30:00Z',
  finishedAt: '2026-07-22T06:31:00Z',
};

const modelRuns: ModelRun[] = [
  {
    id: 21,
    modelKey: 'cross_section_lgbm',
    modelVersion: 'candidate-v1',
    runType: 'train',
    market: 'CN',
    status: 'candidate',
    progress: 100,
    trainStart: '2021-01-01',
    trainEnd: '2025-01-01',
    validStart: null,
    validEnd: null,
    testStart: null,
    testEnd: '2026-01-01',
    metrics: { rankIc: 0.08, top10ExcessReturnPct: 3.2 },
    warnings: [],
    error: null,
    artifactUri: 'quant://models/21',
    createdAt: '2026-07-22T06:30:00Z',
  },
  {
    id: 22,
    modelKey: 'time_series_lgbm',
    modelVersion: 'production-v1',
    runType: 'train',
    market: 'CN',
    status: 'production',
    progress: 100,
    trainStart: '2021-01-01',
    trainEnd: '2025-01-01',
    validStart: null,
    validEnd: null,
    testStart: null,
    testEnd: '2026-01-01',
    metrics: {},
    warnings: [],
    error: null,
    artifactUri: 'quant://models/22',
    createdAt: '2026-07-22T06:30:00Z',
  },
];

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
      { path: '/market/quant/datasets', component: { template: '<div>datasets</div>' } },
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
    vi.mocked(quantApi.deleteModelRun).mockResolvedValue({ id: 21, deleted: true, artifactDeleted: true });
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
      readyDataset,
      { ...readyDataset, id: 9, status: 'building', artifactUri: null, trainable: false },
      { ...readyDataset, id: 10, status: 'ready', artifactUri: null, trainable: false },
    ]);
    vi.mocked(quantApi.createModelRun).mockResolvedValue({
      modelRunId: 19,
      taskId: 'training-task',
      status: 'pending',
      market: 'CN',
    });
  });

  it('shows the entry only to administrators', async () => {
    const { wrapper: userPage } = await mountPage('user');
    expect(userPage.find('[data-testid="open-quant-training"]').exists()).toBe(false);
    userPage.unmount();

    const { wrapper: adminPage } = await mountPage('admin');
    expect(adminPage.get('[data-testid="open-quant-training"]').text()).toContain('创建训练任务');
  });

  it('opens a dialog with only ready datasets that have artifacts', async () => {
    const { wrapper } = await mountPage('admin');

    await wrapper.get('[data-testid="open-quant-training"]').trigger('click');
    await flushPromises();

    expect(wrapper.get('[role="dialog"]').text()).toContain('创建训练任务');
    expect(wrapper.find('[data-testid="quant-training-drawer"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="dataset-build-form"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="dataset-date-from"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="training-dataset-options"]').text()).toContain('#8');
    expect(wrapper.get('[data-testid="training-dataset-options"]').text()).toContain('620,000 行');
    expect(wrapper.get('[data-testid="training-dataset-options"]').text()).not.toContain('#9');
    expect(wrapper.get('[data-testid="training-dataset-options"]').text()).not.toContain('#10');
    expect(wrapper.text()).toContain('Walk-forward');
    expect(wrapper.text()).toContain('Alpha158 + 自定义扩展特征');
  });

  it('creates a training run, closes the dialog, refreshes the model list, and reports success', async () => {
    const { wrapper } = await mountPage('admin');

    await wrapper.get('[data-testid="open-quant-training"]').trigger('click');
    await flushPromises();
    await wrapper.get('[data-testid="training-model-select"]').setValue('cross_section_lgbm');
    await wrapper.get('[data-testid="training-model-version"]').setValue('cn-cross-section-20260722');
    await wrapper.get('[data-testid="training-run-form"]').trigger('submit');
    await flushPromises();

    expect(quantApi.createModelRun).toHaveBeenCalledWith({
      market: 'CN',
      modelKey: 'cross_section_lgbm',
      modelVersion: 'cn-cross-section-20260722',
      datasetSnapshotId: 8,
    });
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    expect(quantApi.models).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain('训练任务已创建');
    expect(wrapper.text()).toContain('ModelRun #19');
  });

  it('shows the empty state and routes to the independent dataset builder', async () => {
    vi.mocked(quantApi.datasets).mockResolvedValue([
      { ...readyDataset, status: 'building', artifactUri: null, trainable: false },
    ]);
    const { wrapper, router } = await mountPage('admin');

    await wrapper.get('[data-testid="open-quant-training"]').trigger('click');
    await flushPromises();

    expect(wrapper.get('[data-testid="training-dataset-empty"]').text()).toContain('当前市场没有已就绪的数据集');
    expect(wrapper.get('[data-testid="training-dataset-empty"]').text()).toContain('前往构建数据集');
    await wrapper.get('[data-testid="training-dataset-empty"] button').trigger('click');
    await flushPromises();

    expect(router.currentRoute.value.path).toBe('/market/quant/datasets');
    expect(router.currentRoute.value.query).toMatchObject({ market: 'CN', build: '1' });
  });

  it('deletes a candidate run with confirmation and protects production', async () => {
    vi.mocked(quantApi.models).mockResolvedValue(modelRuns);
    const { wrapper } = await mountPage('admin');

    expect(wrapper.get('[data-testid="delete-model-run-22"]').attributes('disabled')).toBeDefined();
    await wrapper.get('[data-testid="delete-model-run-21"]').trigger('click');
    expect(wrapper.get('[role="alertdialog"]').text()).toContain('预测和发布关联记录');
    await wrapper.get('[data-testid="confirm-delete"]').trigger('click');
    await flushPromises();

    expect(quantApi.deleteModelRun).toHaveBeenCalledWith(21, 'CN');
    expect(wrapper.text()).toContain('模型运行 #21 及其制品已删除');
    expect(wrapper.find('[data-testid="delete-model-run-21"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="delete-model-run-22"]').exists()).toBe(true);
  });
});
