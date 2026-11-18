import { expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import OpportunityPanel from '../OpportunityPanel.vue';
import { entryLabel, entryScore, entryBranch, entryReason, rowDirectionValue } from '../labels';
import { simulationOperations } from '../simulationMarkers';
import type { IntradayOptionRow, OpportunityBranch, SimulationPlan, SimulationSnapshot, SimTrade } from '@/api/intradayOptions';

const branch: OpportunityBranch = {
  kind: 'trend_continuation', direction: 'bearish', status: 'confirmed', structureId: 'continuation:1',
  trigger: 100, invalidation: 101, atr: .5, formationStart: '2026-11-17T15:00:00Z',
  startedAt: '2026-11-17T15:03:00Z', confirmedAt: '2026-11-17T15:04:00Z', expiresAt: '2026-11-17T15:13:00Z',
  confirmationMethod: 'strong_break', qualityScore: 80, distanceAtr: .5, riskAtr: 1.5,
  components: {}, reasons: [], structureStart: '2026-11-17T15:00:00Z', structureEnd: '2026-11-17T15:03:00Z',
  structureHigh: 100.9, structureLow: 100, atrSource: 'observed_adjacent_true_ranges', atrSamples: 18,
};
const opportunities = { version: 'intraday_entry_v3', primary: branch, branches: [branch], reference: false,
  missingBars: 0, asOf: branch.confirmedAt!, reasons: [] };
const plan: SimulationPlan = { ...branch, processId: 'trend:1', entryLow: 99.6, entryHigh: 99.925,
  target: null, targetSource: '未知', remainingSpace: null, rewardRisk: null, ageSeconds: 5,
  executable: false, opportunityValid: true, executionReason: '当前报价到结构失效位超过2 ATR，风险距离过大' };
const trade: SimTrade = { id: 'one', opportunityId: branch.structureId, symbol: 'NVDA.US', side: -1,
  kind: 'trend_continuation', confirmationMethod: 'strong_break', entryAt: branch.confirmedAt!, entryPrice: 99.8,
  lastPrice: 99.8, lastPriceAt: branch.confirmedAt!, invalidation: 101, protection: 101, target: null, returnPct: 0 };

it('shows strong confirmation, observed volatility and the distinct current execution rejection', () => {
  const wrapper = mount(OpportunityPanel, { props: { opportunities, plans: [plan], stale: false } });
  expect(wrapper.text()).toContain('趋势延续');
  expect(wrapper.text()).toContain('强突破单根确认');
  expect(wrapper.text()).toContain('18 个真实相邻波动样本');
  expect(wrapper.text()).toContain('风险距离过大');
  expect(wrapper.text()).toContain('形态确认不等于当前可进场');
});

it('keeps held opportunity scores and distinguishes current non-execution from historical confirmation', () => {
  const row: IntradayOptionRow = { symbol: 'NVDA.US', name: 'NVIDIA', lastPrice: 99.8, changePct: -1,
    quoteTime: branch.confirmedAt, issues: [], dataStatus: 'ready', quoteStatus: 'ready', opportunityEligible: true,
    rankedOpportunity: { ...branch, opportunityReason: '可以模拟进场', executionReason: '已模拟持有，禁止重复进场或反手' },
    result: { opportunities, version: 'intraday_options_v10', symbol: 'NVDA.US', tradingDate: '2026-11-17',
      asOf: branch.confirmedAt!, observedAt: branch.confirmedAt!, windows: [], score: 80, direction: 'bearish',
      state: 'continuing', baseScore: 80, alignment: 1, extensionAtr: .5, explanation: '' },
    simulation: { symbol: 'NVDA.US', calculatedAt: branch.confirmedAt!, cutoff: '2026-11-17T19:00:00Z',
      currentPrice: 99.8, quoteTime: branch.confirmedAt, stopped: false, position: trade, plans: [plan] } };
  expect(entryScore(row)).toBe(80);
  expect(entryLabel(row)).toBe('已进场/持有中');
  // A is the highest-quality confirmed shape; B (the ranked branch) actually entered.
  row.result!.opportunities = { ...opportunities,
    primary: { ...branch, structureId: 'A', direction: 'bullish', qualityScore: 99 } };
  row.result!.direction = 'bullish';
  expect(entryScore(row)).toBe(80);
  expect(entryBranch(row)?.structureId).toBe(branch.structureId);
  expect(rowDirectionValue(row)).toBe('bearish');
  expect(entryLabel(row)).toBe('已进场/持有中');
  expect(entryReason(row)).toContain('已模拟持有');
  row.result!.opportunities = opportunities;
  row.opportunityEligible = false;
  row.rankedOpportunity = null;
  expect(entryScore(row)).toBeNull();
  expect(entryLabel(row)).toBe('形态确认 · 当前不可执行');
  expect(entryLabel(row, true)).toBe('历史/参考确认');
});

it('carries continuation kind and confirmation method through simulated chart trade details', () => {
  const snapshot: SimulationSnapshot = { states: [], events: [], statistics: [], trades: [trade] };
  const ops = simulationOperations(snapshot, 'NVDA.US', '2026-11-17');
  expect(ops[0]!.action).toBe('S');
  expect(ops[0]!.reason).toContain('趋势延续');
  expect(ops[0]!.reason).toContain('强突破单根确认');
});

it('keeps an executable opening break visible during the longer windows’ warmup', () => {
  const opening = { ...branch, kind: 'opening_breakout' as const, confirmationMethod: 'level_close' as const };
  const row: IntradayOptionRow = { symbol: 'QQQ.US', name: null, lastPrice: 100, changePct: null,
    quoteTime: opening.confirmedAt, issues: [], opportunityEligible: true, dataStatus: 'warming', quoteStatus: 'ready',
    rankedOpportunity: { ...opening, opportunityReason: '', executionReason: '' },
    result: { opportunities: { ...opportunities, reference: true, branches: [opening], primary: opening },
      version: 'intraday_options_v14', symbol: 'QQQ.US', tradingDate: '2026-11-17', asOf: opening.confirmedAt!,
      observedAt: opening.confirmedAt!, windows: [], score: null, direction: null, state: null, baseScore: null,
      alignment: null, extensionAtr: null, explanation: '' },
  };
  expect(entryScore(row)).toBe(opening.qualityScore);
  expect(entryLabel(row)).toBe('已确认');
});
