import { createPinia, setActivePinia } from 'pinia';
import { useMarketStore } from '@/stores/marketStore';
import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';
import WatchListPage from '../WatchListPage.vue';
import WatchListTagPicker from '@/components/watch-list/WatchListTagPicker.vue';
import WatchListTagManager from '@/components/watch-list/WatchListTagManager.vue';
import StockAutocomplete from '@/components/StockAutocomplete/StockAutocomplete.vue';
import type { WatchListFilters, WatchListItem, WatchListTag } from '@/api/watchList';

const mocks = vi.hoisted(() => ({
  list: vi.fn(), listTags: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(),
  streamOptions: null as unknown,
}));
vi.mock('@/api/watchList', () => ({ watchListApi: mocks }));
vi.mock('@/composables/useRealtimeQuotes', async () => {
  const { ref } = await import('vue');
  return { useRealtimeQuotes: (options: unknown) => {
    mocks.streamOptions = options;
    return { getQuote: () => undefined, status: ref('connected') };
  } };
});
const tags: WatchListTag[] = [{ id: 1, name: '科技' }, { id: 2, name: '长期' }, { id: 3, name: '空标签' }];
const item = (id: number, market: 'CN' | 'US', labels: WatchListTag[] = []): WatchListItem => ({
  id, code: market === 'CN' ? `60000${id}.SH` : `US${id}.US`, name: `股票${id}`, marketType: market,
  tags: labels, notes: '备注', isFavorite: id === 2, createdAt: `${id}`, updatedAt: `${id}`,
});
let rows: WatchListItem[];
const stubs = {
  StockDetailDialog: true, StockAutocomplete: true,
  Dialog: { props: ['open'], template: '<div v-if="open"><slot /></div>' },
  DialogContent: { template: '<div><slot /></div>' },
  DialogHeader: { template: '<div><slot /></div>' },
  DialogTitle: { template: '<div><slot /></div>' },
  DialogDescription: { template: '<div><slot /></div>' },
  DialogFooter: { template: '<div><slot /></div>' },
  DropdownMenu: { template: '<div><slot /></div>' },
  DropdownMenuTrigger: { template: '<div><slot /></div>' },
  DropdownMenuContent: { template: '<div><slot /></div>' },
  DropdownMenuItem: { template: '<button @click="$emit(\'select\')"><slot /></button>' },
};
async function mountPage() {
  const page = mount(WatchListPage, { global: { stubs } });
  await flushPromises();
  return page;
}
function streamFilters() { return (mocks.streamOptions as () => unknown)(); }

beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
  rows = [item(1, 'CN', [tags[0]!]), item(2, 'CN'), item(3, 'US', [tags[0]!, tags[1]!])];
  mocks.listTags.mockResolvedValue(tags);
  mocks.list.mockImplementation(async (filters: WatchListFilters) => {
    const all = rows.filter(row => row.marketType === filters.market);
    return { total: all.length, items: all.filter(row => filters.ungrouped ? !row.tags.length
      : filters.tagId !== undefined ? row.tags.some(tag => tag.id === filters.tagId) : true) };
  });
  mocks.update.mockImplementation(async (id: number, body: { tags?: { id?: number; name?: string }[]; notes?: string; isFavorite?: boolean }) => {
    const row = rows.find(row => row.id === id)!;
    const saved = { ...row, ...body, tags: body.tags?.map(tag => tag.id ? tags.find(t => t.id === tag.id)! : { id: 4, name: tag.name! }) ?? row.tags };
    rows = rows.map(row => row.id === id ? saved : row);
    return saved;
  });
});
afterEach(() => { vi.clearAllMocks(); });

describe('watch-list market and group selection', () => {
  it('defaults to CN with All first, filters on the server and stream, retains groups on market switches', async () => {
    const page = await mountPage();
    expect(useMarketStore().market).toBe('CN');
    expect(page.find('[aria-label="自选股市场"]').exists()).toBe(false);
    expect(page.get('[data-testid=tag-filters] button').text()).toBe('全部');
    expect(page.get('[data-testid=tag-filters] button').attributes('aria-pressed')).toBe('true');
    expect(page.get('[data-testid=watch-list-count]').text()).toBe('显示 2 / 2 只');
    expect(page.findAll('tbody tr[tabindex]').map(row => row.text())).toEqual([expect.stringContaining('股票2'), expect.stringContaining('股票1')]);
    await page.findAll('[data-testid=tag-filters] button').find(b => b.text() === '科技')!.trigger('click');
    await flushPromises();
    expect(mocks.list).toHaveBeenLastCalledWith({ market: 'CN', tagId: 1, ungrouped: false }, expect.any(AbortSignal));
    expect(streamFilters()).toEqual({ scope: 'watch-list', market: 'CN', tagId: 1, ungrouped: false });
    expect(page.get('[data-testid=watch-list-count]').text()).toBe('显示 1 / 2 只');
    useMarketStore().market = 'US';
    await flushPromises();
    expect(streamFilters()).toEqual({ scope: 'watch-list', market: 'US', tagId: 1, ungrouped: false });
    expect(page.get('tbody').text()).toContain('股票3');
    expect(page.findAll('[data-testid=stock-tags] span').map(tag => tag.text())).toEqual(['科技', '长期']);
    await page.findAll('[data-testid=tag-filters] button').find(b => b.text() === '未分组')!.trigger('click');
    await flushPromises();
    expect(page.text()).toContain('当前分组暂无自选股');
    expect(page.get('[data-testid=watch-list-count]').text()).toBe('显示 0 / 1 只');
    expect(streamFilters()).toEqual({ scope: 'watch-list', market: 'US', tagId: undefined, ungrouped: true });
    page.unmount();
  });

  it('keeps market, group and add controls visible in an empty market', async () => {
    rows = [];
    const page = await mountPage();
    expect(page.text()).toContain('当前市场暂无自选股');
    expect(page.text()).toContain('空标签');
    useMarketStore().market = 'US';
    await nextTick();
    await page.findAll('button').find(b => b.text() === '添加')!.trigger('click');
    expect(page.findComponent(StockAutocomplete).props('market')).toBe('US');
    page.findComponent(StockAutocomplete).vm.$emit('submit', '00700.HK', '腾讯', 'autocomplete', 'HK');
    await nextTick();
    await page.findAll('button').find(b => b.text() === '保存')!.trigger('click');
    expect(mocks.create).not.toHaveBeenCalled();
    page.unmount();
  });

  it('stages labels and notes, cancels without writes, saves complete labels and displays persisted results', async () => {
    const page = await mountPage();
    const edit = () => page.findAll('tbody button').find(b => b.text() === '编辑')!.trigger('click');
    await edit();
    let picker = page.findComponent(WatchListTagPicker);
    picker.vm.$emit('update:modelValue', [{ id: 1, name: '科技' }, { name: '新标签' }]);
    await nextTick();
    await page.findAll('button').find(b => b.text() === '取消')!.trigger('click');
    expect(mocks.update).not.toHaveBeenCalled();
    expect(mocks.create).not.toHaveBeenCalled();
    expect(page.get('[data-testid=tag-filters]').text()).not.toContain('新标签');
    await edit();
    picker = page.findComponent(WatchListTagPicker);
    expect(picker.props('modelValue')).toEqual([]); // Favorite row is ungrouped.
    picker.vm.$emit('update:modelValue', [{ id: 1, name: '科技' }, { name: '新标签' }]);
    await page.get('#watchlist-notes').setValue('新备注');
    await page.findAll('button').find(b => b.text() === '保存')!.trigger('click');
    await flushPromises();
    expect(mocks.update).toHaveBeenCalledWith(2, { notes: '新备注', tags: [{ id: 1 }, { name: '新标签' }] });
    expect(page.get('[data-testid=tag-filters]').text()).toContain('新标签');
    await edit();
    expect(page.findComponent(WatchListTagPicker).props('modelValue')).toEqual([{ id: 1, name: '科技' }, { id: 4, name: '新标签' }]);
    page.unmount();
  });

  it('synchronizes renaming and returns to All after deleting the selected tag', async () => {
    const page = await mountPage();
    await page.findAll('[data-testid=tag-filters] button').find(b => b.text() === '科技')!.trigger('click');
    await flushPromises();
    await page.findAll('button').find(b => b.text() === '管理标签')!.trigger('click');
    page.findComponent(WatchListTagManager).vm.$emit('renamed', { id: 1, name: '新科技' });
    await nextTick();
    expect(page.get('[data-testid=tag-filters]').text()).toContain('新科技');
    expect(page.get('[data-testid=stock-tags]').text()).toBe('新科技');
    page.findComponent(WatchListTagManager).vm.$emit('deleted', 1);
    await flushPromises();
    expect(page.get('[data-testid=tag-filters] button').attributes('aria-pressed')).toBe('true');
    expect(streamFilters()).toMatchObject({ tagId: undefined, ungrouped: false });
    page.unmount();
  });

  it('ignores stale list responses after a quick market switch', async () => {
    let resolveOld!: (value: unknown) => void;
    mocks.list.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const page = await mountPage();
    useMarketStore().market = 'US';
    await flushPromises();
    resolveOld({ items: [item(9, 'CN')], total: 99 });
    await flushPromises();
    expect(page.get('tbody').text()).toContain('股票3');
    expect(page.text()).not.toContain('股票9');
    page.unmount();
  });
});
