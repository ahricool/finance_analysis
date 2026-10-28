import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import PositionsPlan from '../PositionsPlan.vue';
import { adapt, type Detail } from '@/api/stockStrategies';
import { detail as raw } from '../../../../e2e/fixtures/stockStrategies';
function fixture() {
  const d = adapt<Detail>(structuredClone(raw));
  d.latest!.payload.plan.candidates = Array.from({ length: 40 }, (_, i) => ({ code: `S${i}.US`, name: `候选${i}`, score: i, signalClose: 100, atr: 1, type: 'STOCK' }));
  return d;
}
const mountPlan = (detail: Detail) => mount(PositionsPlan, { props: { detail }, global: { stubs: { StockLink: { props: ['code', 'name'], template: '<span>{{ name }} {{ code }}</span>' } } } });
describe('positions and frozen plan', () => {
  it('shows five of forty candidates for one slot, preserves order and expands all', async () => {
    const wrapper = mountPlan(fixture());
    expect(wrapper.findAll('[data-testid="strategy-candidate"]')).toHaveLength(5);
    expect(wrapper.text()).toContain('已满仓');
    expect(wrapper.text()).toContain('非买入清单');
    expect(wrapper.text()).toContain('计划卖出尚未释放仓位或资金');
    await wrapper.find('button').trigger('click');
    expect(wrapper.findAll('[data-testid="strategy-candidate"]')).toHaveLength(40);
    expect(wrapper.findAll('[data-testid="strategy-candidate"]')[39]!.text()).toContain('S39.US');
  });
  it('keeps paused, blocked exit, stale valuation and historical states visible together', () => {
    const d = fixture(); const payload = d.latest!.payload;
    payload.plan.status = 'PAUSED'; payload.nextIsHistorical = true;
    payload.positions['AAPL.US']!.pendingExit = ['卖出开盘不可交易'];
    payload.positions['AAPL.US']!.markDate = '2026-10-16';
    const wrapper = mountPlan(d);
    expect(wrapper.text()).toContain('暂停新增：');
    expect(wrapper.text()).toContain('存在待退出持仓');
    expect(wrapper.text()).toContain('估值过期');
    expect(wrapper.find('h2:nth-of-type(1)').text()).toBe('当前模拟持仓');
    expect(wrapper.find('[data-testid="strategy-plan"] h2').text()).toBe('历史补算计划（非当前待执行）');
    expect(wrapper.text()).not.toContain('下一交易日模拟计划');
  });
  it('distinguishes settled flat, no candidates, and no successful settlement', async () => {
    const d = fixture(); d.latest!.payload.positions = {}; d.latest!.payload.plan.candidates = [];
    const wrapper = mountPlan(d);
    expect(wrapper.text()).toContain('当前空仓'); expect(wrapper.text()).toContain('无新增候选');
    await wrapper.setProps({ detail: { ...d, latest: null } });
    expect(wrapper.text()).not.toContain('当前空仓'); expect(wrapper.text()).toContain('尚未生成计划');
  });
  it('does not promote an overdue frozen plan as the next trading day plan', () => {
    const d = fixture(); d.expectedDate = '2026-10-21';
    const wrapper = mountPlan(d);
    expect(wrapper.find('[data-testid="strategy-plan"] h2').text()).toBe('此前冻结计划（等待结算）');
    expect(wrapper.text()).toContain('不是未来交易日的新计划');
  });

});
