import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { watchListApi } from '@/api/watchList';
import WatchListTagPicker from '../WatchListTagPicker.vue';
import WatchListTagManager from '../WatchListTagManager.vue';

vi.mock('@/api/watchList', () => ({ watchListApi: { createTag: vi.fn(), renameTag: vi.fn(), deleteTag: vi.fn() } }));
afterEach(() => vi.clearAllMocks());
const tags = [{ id: 1, name: 'Growth' }, { id: 2, name: '科技' }];

it('searches, toggles, creates draft labels and removes selections without API writes', async () => {
  const page = mount(WatchListTagPicker, { props: { tags, modelValue: [] } });
  await page.get('input').setValue('growth');
  expect(page.findAll('[aria-label="选择分组标签"] button')).toHaveLength(1);
  expect(page.text()).not.toContain('创建并选中');
  await page.get('[aria-label="选择分组标签"] button').trigger('click');
  expect(page.emitted('update:modelValue')?.at(-1)).toEqual([[tags[0]]]);
  await page.setProps({ modelValue: [tags[0]!] });
  await page.get('input').setValue(' 新分组 ');
  await page.findAll('button').find(b => b.text().includes('创建并选中'))!.trigger('click');
  expect(page.emitted('update:modelValue')?.at(-1)).toEqual([[tags[0], { name: '新分组' }]]);
  await page.get('[aria-label="移除标签 Growth"]').trigger('click');
  expect(page.emitted('update:modelValue')?.at(-1)).toEqual([[]]);
  expect(watchListApi.createTag).not.toHaveBeenCalled();
  page.unmount();
});

describe('label manager', () => {
  const stubs = {
    Dialog: { template: '<div><slot /></div>' }, DialogContent: { template: '<div><slot /></div>' },
    DialogHeader: { template: '<div><slot /></div>' }, DialogTitle: { template: '<div><slot /></div>' },
    DialogDescription: { template: '<div><slot /></div>' },
    AppConfirmDialog: { props: ['open', 'description'], template: '<div v-if="open">{{ description }}<button @click="$emit(\'confirm\')">确认删除</button></div>' },
  };
  it('creates and renames via scoped API, deletes only after confirmation', async () => {
    vi.mocked(watchListApi.createTag).mockResolvedValue({ id: 3, name: '其他' });
    vi.mocked(watchListApi.renameTag).mockResolvedValue({ id: 1, name: '成长' });
    vi.mocked(watchListApi.deleteTag).mockResolvedValue();
    const page = mount(WatchListTagManager, { props: { open: true, tags }, global: { stubs } });
    await page.get('input').setValue(' 其他 ');
    await page.findAll('button').find(b => b.text() === '创建')!.trigger('click');
    await flushPromises();
    expect(watchListApi.createTag).toHaveBeenCalledWith('其他');
    expect(page.emitted('created')).toEqual([[{ id: 3, name: '其他' }]]);
    await page.get('[aria-label="重命名 Growth"]').trigger('click');
    await page.get('input[aria-label="重命名 Growth"]').setValue(' 成长 ');
    await page.findAll('button').find(b => b.text() === '保存')!.trigger('click');
    await flushPromises();
    expect(watchListApi.renameTag).toHaveBeenCalledWith(1, '成长');
    await page.get('[aria-label="删除标签 科技"]').trigger('click');
    expect(page.text()).toContain('会移除全部股票上的该标签，但不会删除股票');
    expect(watchListApi.deleteTag).not.toHaveBeenCalled();
    await page.findAll('button').find(b => b.text() === '确认删除')!.trigger('click');
    await flushPromises();
    expect(watchListApi.deleteTag).toHaveBeenCalledWith(2);
    expect(page.emitted('deleted')).toEqual([[2]]);
    page.unmount();
  });
});
