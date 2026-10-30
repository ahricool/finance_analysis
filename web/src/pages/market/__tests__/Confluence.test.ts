import { useMarketStore } from '@/stores/marketStore';
import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia } from 'pinia';
import Page from '../ConfluencePage.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import { confluenceApi as api, type ConfluenceRanking } from '@/api/confluence';
import { toCamelCase } from '@/api/utils';
import research from '../../../../e2e/fixtures/confluenceV22';
import adapted from '../../../../e2e/fixtures/confluenceV21';
import v2 from '../../../../e2e/fixtures/confluenceV2';
import raw from '../../../../e2e/fixtures/confluence';

vi.mock('@/api/confluence', () => ({ confluenceApi: { ranking: vi.fn(), dates: vi.fn(), run: vi.fn() } }));
const auth = vi.hoisted(() => ({ currentUser: { role: 'user' } }));
vi.mock('@/composables/useAuth', () => ({ useAuth: () => auth }));
const ranking = toCamelCase<ConfluenceRanking>(raw);
const mountPage = () => mount(Page, { global: { plugins: [createPinia()], stubs: { StockDetailDialog: true } } });
beforeEach(() => {
  vi.clearAllMocks(); auth.currentUser.role = 'user';
  vi.mocked(api.ranking).mockResolvedValue(ranking);
  vi.mocked(api.dates).mockResolvedValue(['2026-09-22', '2026-09-21']);
});
describe('confluence controls and detail', () => {
  it('reloads on date and market changes, resetting the snapshot-specific minimum', async () => {
    const wrapper = mountPage();
    await flushPromises();
    const picker = wrapper.getComponent(AppDatePicker);
    expect(picker.props('availableDates')).toEqual(['2026-09-22', '2026-09-21']);
    expect(picker.props('disableWeekends')).toBe(true);
    await wrapper.get('input[aria-label="最低有效维度"]').setValue(5);
    picker.vm.$emit('update:modelValue', '2026-09-21');
    await flushPromises();
    expect(api.ranking).toHaveBeenLastCalledWith(expect.objectContaining({ market: 'CN', trade_date: '2026-09-21', min_signals: undefined }));
    useMarketStore().market = 'US';
    await flushPromises();
    expect(api.ranking).toHaveBeenLastCalledWith(expect.objectContaining({ market: 'US', trade_date: undefined, min_signals: undefined }));
    expect(api.dates).toHaveBeenLastCalledWith('US');
    expect(wrapper.find('select[aria-label="市场"]').exists()).toBe(false);
    wrapper.unmount();
  });
  it('opens the shared confluence tab with the source identity and historical context', async () => {
    const wrapper = mountPage();
    await flushPromises();
    expect(wrapper.getComponent(StockDetailDialog).props('open')).toBe(false);
    await wrapper.get('tbody button').trigger('click');
    await flushPromises();
    const dialog = wrapper.getComponent(StockDetailDialog);
    expect(dialog.props('open')).toBe(true);
    expect(dialog.props('stock')).toMatchObject({ code: '600001.SH', marketType: 'CN' });
    expect(dialog.props('initialTab')).toBe('overview');
  await wrapper.get('tbody tr').trigger('click');
  expect(dialog.props('initialTab')).toBe('confluence');
    expect(dialog.props('context')).toEqual({ tradeDate: '2026-09-22', view: 'official' });
    dialog.vm.$emit('update:open', false);
    await flushPromises();
    expect(dialog.props('open')).toBe(false);
    wrapper.unmount();
  });
  it('keeps macro context visible even when no daily signal qualifies', async () => {
    vi.mocked(api.ranking).mockResolvedValue({ ...ranking, algorithmVersion: 'confluence_v2', items: [], total: 0,
      sourceAvailability: { macro: { status: 'available', count: 1, tradeDate: '2026-09-21', evidence: { regime: 'RISK_ON' } } },
      summary: { ...ranking.summary, total: 0, eligible: 0, strongConfluence: 0 } });
    const wrapper = mountPage(); await flushPromises();
    expect(wrapper.text()).toContain('RISK_ON');
    expect(wrapper.text()).toContain('暂无符合条件的高一致性信号');
    wrapper.unmount();
  });
  it('labels historical snapshots and uses their saved weights', async () => {
    const wrapper = mountPage(); await flushPromises();
    expect(wrapper.text()).toContain('历史版本');
    expect(wrapper.text()).toContain('基础权重 70%');
    expect(wrapper.text()).toContain('基础权重 30%');
    wrapper.unmount();
  });

  it('labels V2 historical macro semantics without reinterpreting its scores', async () => {
    vi.mocked(api.ranking).mockResolvedValue(toCamelCase<ConfluenceRanking>(v2));
    const wrapper = mountPage(); await flushPromises();
    expect(wrapper.text()).toContain('统一风险偏好分');
    expect(wrapper.text()).not.toContain('个股使用所属行业宏观适配度评分');
    wrapper.unmount();
  });
  it('recognizes V2.1 as current and distinguishes global context from per-stock fit', async () => {
    vi.mocked(api.ranking).mockResolvedValue(toCamelCase<ConfluenceRanking>(adapted));
    const wrapper = mountPage(); await flushPromises();
    expect(wrapper.text()).toContain('个股使用所属行业宏观适配度评分');
    expect(wrapper.text()).toContain('宏观适配');
    expect(wrapper.text()).not.toContain('历史版本');
    expect(wrapper.text()).not.toContain('统一风险偏好分');
    wrapper.unmount();
  });

  it('paginates fifty research rows, labels below-threshold observations and keeps selected count separate', async () => {
    vi.mocked(api.ranking).mockResolvedValue(toCamelCase<ConfluenceRanking>(research));
    const wrapper = mountPage(); await flushPromises();
    expect(api.ranking).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 50, min_score: 0 }));
    expect(wrapper.findAll('tbody tr')).toHaveLength(10);
    expect(wrapper.get('[data-testid="selected-count"]').text().replace(/\s/g, '')).toBe('10/10');
    expect(wrapper.get('[data-testid="confluence-pagination"]').text()).toContain('第 1 / 5 页');
    const buttons = () => wrapper.get('[data-testid="confluence-pagination"]').findAll('button');
    expect(buttons()[0]!.attributes('disabled')).toBeDefined();
    await buttons()[1]!.trigger('click');
    expect(wrapper.find('tbody tr').text()).toContain('观察股票11');
    expect(wrapper.find('tbody tr').text()).toContain('11');
    await buttons()[1]!.trigger('click');
    expect(wrapper.get('[data-testid="confluence-pagination"]').text()).toContain('第 3 / 5 页');
    expect(wrapper.findAll('[data-testid="below-threshold"]')).toHaveLength(10);
    expect(wrapper.find('tbody tr').text()).toContain('低于60分');
    expect(wrapper.find('tbody tr').text()).toContain('59.99');
    await wrapper.get('tbody tr').trigger('click');
    expect(wrapper.getComponent(StockDetailDialog).props('stock')?.code).toBe('600021.SH');
    wrapper.getComponent(StockDetailDialog).vm.$emit('update:open', false);
    await buttons()[1]!.trigger('click'); await buttons()[1]!.trigger('click');
    expect(wrapper.get('[data-testid="confluence-pagination"]').text()).toContain('第 5 / 5 页');
    expect(buttons()[1]!.attributes('disabled')).toBeDefined();
    wrapper.getComponent(AppDatePicker).vm.$emit('update:modelValue', '2026-09-21'); await flushPromises();
    expect(wrapper.get('[data-testid="confluence-pagination"]').text()).toContain('第 1 / 5 页');
    wrapper.unmount();
  });

});


it('ignores an old market task submission after switching away and back', async () => {
  auth.currentUser.role = 'admin';
  let resolveOld!: (value: { taskId: string }) => void;
  vi.mocked(api.run).mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
  const wrapper = mountPage(); await flushPromises();
  await wrapper.findAll('button').find(button => button.text() === '生成信号')!.trigger('click');
  useMarketStore().market = 'US'; await flushPromises();
  useMarketStore().market = 'CN'; await flushPromises();
  resolveOld({ taskId: 'stale-cn-task' }); await flushPromises();
  expect(wrapper.text()).not.toContain('stale-cn-task');
  expect(wrapper.findAll('button').some(button => button.text() === '生成信号' && button.attributes('disabled') === undefined)).toBe(true);
  wrapper.unmount();
});
