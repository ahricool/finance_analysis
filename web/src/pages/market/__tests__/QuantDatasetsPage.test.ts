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
    deleteDataset: vi.fn(),
    buildDataset: vi.fn(),
    modelDefinitions: vi.fn(),
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

vi.mock('@/components/app/AppDatePicker.vue', () => ({
  default: {
    inheritAttrs: false,
    props: ['modelValue', 'label'],
    emits: ['update:modelValue'],
    template: '<label>{{ label }}<input v-bind="$attrs" type="text" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" /></label>',
  },
}));

vi.mock('@/components/forms/FieldSelect.vue', () => ({
  default: {
    inheritAttrs: false,
    props: ['modelValue', 'options', 'label'],
    emits: ['update:modelValue'],
    template: '<label>{{ label }}<select v-bind="$attrs" :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><option v-for="item in options" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>',
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
    universeMemberCount: 302,
    universeCoverageRatio: 300 / 302,
    minimumUniverseCoverage: 0.9,
    trainable: true,
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
    universeMemberCount: 302,
    universeCoverageRatio: 0,
    minimumUniverseCoverage: 0.9,
    trainable: false,
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
    vi.mocked(quantApi.deleteDataset).mockResolvedValue({ id: 8, deleted: true, artifactDeleted: true });
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

  it('opens the build dialog with the default three-year range', async () => {
    const { wrapper } = await mountPage();

    await wrapper.get('[data-testid="open-dataset-build"]').trigger('click');

    expect(wrapper.get('[role="dialog"]').text()).toContain('构建数据集');
    expect(wrapper.get('[data-testid="dataset-date-from"]').element).toHaveProperty('value', '2023-07-22');
    expect(wrapper.get('[data-testid="dataset-date-to"]').element).toHaveProperty('value', '2026-07-22');
    expect(wrapper.get('[data-testid="dataset-universe"]').element).toHaveProperty('value', '沪深300 / cn_csi300');
    expect(wrapper.find('[data-testid="quant-training-drawer"]').exists()).toBe(false);
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

  it('confirms deletion, removes the row, and keeps active datasets protected', async () => {
    const { wrapper } = await mountPage();

    expect(wrapper.get('[data-testid="delete-dataset-9"]').attributes('disabled')).toBeDefined();
    await wrapper.get('[data-testid="delete-dataset-desktop-8"]').trigger('click');
    expect(wrapper.get('[role="alertdialog"]').text()).toContain('数据库记录和 /data 下对应制品');
    await wrapper.get('[data-testid="confirm-delete"]').trigger('click');
    await flushPromises();

    expect(quantApi.deleteDataset).toHaveBeenCalledWith(8, 'CN');
    expect(wrapper.text()).toContain('数据集 #8 及其制品已删除');
    expect(wrapper.find('[data-testid="delete-dataset-desktop-8"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="delete-dataset-9"]').exists()).toBe(true);
  });
});
