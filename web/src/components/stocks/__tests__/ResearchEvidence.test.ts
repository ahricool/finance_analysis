import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ResearchEvidence from '../ResearchEvidence.vue';
const api = vi.hoisted(() => ({ trend: vi.fn(), etf: vi.fn(), quant: vi.fn(), industry: vi.fn(), signals: vi.fn() }));
vi.mock('@/api/trendFollowing', () => ({ trendFollowingApi: { detail: api.trend } }));
vi.mock('@/api/etfRotation', () => ({ etfRotationApi: { detail: api.etf } }));
vi.mock('@/api/quant', () => ({ quantApi: { signal: api.quant } }));
vi.mock('@/api/industryStrength', () => ({ industryStrengthApi: { stockContext: api.industry } }));
vi.mock('@/api/holdings', () => ({ tradeEngineApi: { signals: api.signals } }));
let wrapper: VueWrapper;
function mountEvidence(props = { symbol: '600519.SH', market: 'CN', positionId: 11 as number | undefined }) {
  wrapper = mount(ResearchEvidence, { props, global: { plugins: [createPinia()], stubs: { RouterLink: { props: ['to'], template: '<a :href="to.path + `?` + new URLSearchParams(to.query)"><slot /></a>', setup: () => ({ URLSearchParams }) } } } });
  return flushPromises();
}
beforeEach(() => {
  vi.resetAllMocks();
  api.trend.mockResolvedValue({ latest: { tradeDate: '2026-09-21', state: 'TRENDING', rank: 5, alphaScore: 81, reasons: ['趋势增强'] } });
  api.etf.mockRejectedValue({ response: { status: 404 } });
  api.quant.mockResolvedValue({ tradeDate: '2026-09-18', signal: 'WATCH', finalScore: 72, modelVersion: 'v2', reasons: ['量化依据'] });
  api.industry.mockResolvedValue([{ industryCode: '881101.TI', industryName: '食品', tradeDate: '2026-09-21', state: 'STRONG', strengthRank: 2, strengthScore: 80, membersObservedAt: '2026-09-21T10:00:00Z' }]);
  api.signals.mockResolvedValue([]);
});
afterEach(() => wrapper?.unmount());

describe('ResearchEvidence', () => {
  it('shows dated independent evidence, coverage gaps, and source links pinned to the date', async () => {
    await mountEvidence();
    expect(wrapper.text()).toContain('各模块数据日期不一致');
    expect(wrapper.text()).toContain('趋势增强');
    expect(wrapper.text()).toContain('食品');
    expect(wrapper.get('[data-testid="evidence-etf"]').text()).toContain('暂无正式结果');
    expect(wrapper.find('a[href*="trend-following"]').attributes('href')).toContain('tradeDate=2026-09-21');
    expect(wrapper.find('a[href*="trend-following"]').attributes('href')).toContain('symbol=600519.SH');
    expect(wrapper.find('a[href*="quant/signals"]').attributes('href')).toContain('market=CN');
    expect(api.signals).toHaveBeenCalledWith('CN', '11');
  });

  it('exposes source failures and retries without reloading other modules', async () => {
    api.trend.mockRejectedValueOnce(new Error('offline'));
    await mountEvidence();
    expect(wrapper.get('[data-testid="evidence-trend"]').text()).toContain('重试趋势跟踪');
    const buttons = wrapper.get('[data-testid="evidence-trend"]').findAll('button');
    await buttons[buttons.length - 1]!.trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('趋势增强');
    expect(api.quant).toHaveBeenCalledTimes(1);
  });

  it('keeps historical stored signal evidence separate and filters mismatched positions', async () => {
    api.signals.mockResolvedValue([
      { id: 1, symbol: '600519.SH', positionId: '11', evaluatedAt: '2026-09-17T10:00:00Z', action: 'REDUCE', strategyKey: 'market_llm', strategyVersion: '1', suggestedTargetQuantity: '5', reason: '当时风险偏高', evidence: { currentQuantity: '10', targetQuantity: '5', portfolioReason: '降低集中度' } },
      { id: 2, symbol: '600519.SH', positionId: '99', reason: 'other position', evidence: {} },
    ]);
    await mountEvidence();
    expect(wrapper.get('[data-testid="signal-evidence"]').text()).toContain('当时风险偏高');
    expect(wrapper.get('[data-testid="signal-evidence"]').text()).not.toContain('趋势增强');
    expect(wrapper.text()).not.toContain('other position');
    expect(wrapper.text()).toContain('当时持仓 10 → 目标 5');
  });

  it('ignores old symbol responses and never requests private signals from watchlist', async () => {
    let finish!: (value: unknown) => void;
    api.trend.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    await mountEvidence({ symbol: '600519.SH', market: 'CN', positionId: undefined });
    await wrapper.setProps({ symbol: 'AAPL.US', market: 'US' });
    await flushPromises();
    finish({ latest: { tradeDate: '2026-09-01', state: 'OLD', reasons: ['过期证据'] } });
    await flushPromises();
    expect(wrapper.text()).not.toContain('过期证据');
    expect(wrapper.text()).not.toContain('食品');
    expect(api.signals).not.toHaveBeenCalled();
    expect(api.industry).toHaveBeenCalledTimes(1);
  });

  it('shows unsupported HK coverage without sending research requests', async () => {
    await mountEvidence({ symbol: '00700.HK', market: 'HK', positionId: undefined });
    expect(wrapper.text()).toContain('港股暂无研究证据');
    expect(api.trend).not.toHaveBeenCalled();
    expect(api.quant).not.toHaveBeenCalled();
  });
});
