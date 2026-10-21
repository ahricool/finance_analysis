import { expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import DragonTigerFlowPage from '../DragonTigerFlowPage.vue';
import { dragonTigerFlowApi } from '@/api/dragonTigerFlow';
import { toCamelCase } from '@/api/utils';
import raw from '../../../../e2e/fixtures/dragonTigerFlow';
vi.mock('@/composables/useAuth', () => ({ useAuth: () => ({ currentUser: null }) }));
vi.mock('@/api/dragonTigerFlow', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/dragonTigerFlow')>();
  return { ...actual, dragonTigerFlowApi: { overview: vi.fn(), dates: vi.fn(), run: vi.fn() } };
});
it('defaults to a single day and exposes all stocks even when the requested long window has gaps', async () => {
  vi.mocked(dragonTigerFlowApi.overview).mockResolvedValue(toCamelCase({ ...raw, complete: false, missing_dates: ['2026-09-15'] }));
  vi.mocked(dragonTigerFlowApi.dates).mockResolvedValue([]);
  const wrapper = mount(DragonTigerFlowPage, { global: { stubs: { FlowCharts: true, RouterLink: true, AppDatePicker: true } } });
  await flushPromises();
  expect(dragonTigerFlowApi.overview).toHaveBeenCalledWith(expect.objectContaining({ days: 1 }));
  expect(wrapper.get('[data-testid="flow-all-stocks"]').findAll('tbody tr')).toHaveLength(16);
  expect(wrapper.get('[data-testid="flow-all-stocks"]').text()).toContain('已采集日净额');
  await wrapper.get('[aria-label="搜索全部上榜股票"]').setValue('600016.SH');
  expect(wrapper.get('[data-testid="flow-all-stocks"]').findAll('tbody tr')).toHaveLength(1);
  expect(wrapper.text()).toContain('游资席位样本');
  wrapper.unmount();
});

it('opens shared stock detail with the exact observed flow filters and source concept', async () => {
  vi.mocked(dragonTigerFlowApi.overview).mockResolvedValue(toCamelCase(raw));
  vi.mocked(dragonTigerFlowApi.dates).mockResolvedValue([]);
  const wrapper = mount(DragonTigerFlowPage, { global: { stubs: { StockDetailDialog: true, FlowCharts: true, RouterLink: true, AppDatePicker: true } } });
  await flushPromises();
  await wrapper.get('[data-testid="flow-stocks"] tbody button').trigger('click');
  const dialog = wrapper.getComponent(StockDetailDialog);
  expect(dialog.props('open')).toBe(true);
  expect(dialog.props('initialTab')).toBe('overview');
  await wrapper.get('[data-testid="flow-stocks"] tbody tr').trigger('click');
  expect(dialog.props('initialTab')).toBe('dragon-tiger');
  expect(dialog.props('context')).toMatchObject({ tradeDate: raw.trade_date, view: 'official', dragonTiger: { endDate: raw.trade_date, days: 1, board: 'all', rangeDays: 1 }, dragonTigerConceptId: raw.concepts[0]!.id });
  dialog.vm.$emit('update:open', false);
  await flushPromises();
  expect(dialog.props('open')).toBe(false);
  wrapper.unmount();
});
