import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia } from 'pinia';
import Page from '../ConfluencePage.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import { confluenceApi as api, type ConfluenceRanking } from '@/api/confluence';
import { toCamelCase } from '@/api/utils';
import raw from '../../../../e2e/fixtures/confluence';

vi.mock('@/api/confluence', () => ({ confluenceApi: { ranking: vi.fn(), dates: vi.fn(), run: vi.fn() } }));
vi.mock('@/composables/useAuth', () => ({ useAuth: () => ({ currentUser: { role: 'user' } }) }));
const ranking = toCamelCase<ConfluenceRanking>(raw);
const mountPage = () => mount(Page, { global: { plugins: [createPinia()], stubs: { StockDetailDialog: true } } });
beforeEach(() => {
  vi.clearAllMocks();
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
    await wrapper.get('[data-testid="confluence-market-switcher"] [role="radio"]').trigger('click');
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
    expect(dialog.props('stock')).toMatchObject({ code: '600001.SH', market_type: 'CN' });
    expect(dialog.props('initialTab')).toBe('overview');
  await wrapper.get('tbody tr').trigger('click');
  expect(dialog.props('initialTab')).toBe('confluence');
    expect(dialog.props('context')).toEqual({ tradeDate: '2026-09-22', view: 'official' });
    dialog.vm.$emit('update:open', false);
    await flushPromises();
    expect(dialog.props('open')).toBe(false);
    wrapper.unmount();
  });
});
