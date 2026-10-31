import { describe, expect, it } from 'vitest';
import { metricHint } from '..';
import { trendIndicatorDescriptions as trend } from '@/components/trend-following/indicatorDescriptions';
import { indicatorDescriptions as etf } from '@/components/etf-rotation/indicatorDescriptions';

const required: Record<string, string[]> = {
  macro: ['macroRegime', 'riskScore', 'signalCoverage', 'rates', 'credit', 'dollar', 'volatility', '趋势', '贡献 / 权重', '1D', '5D', '20D'],
  intraday: ['候选总数', 'CONFIRMED', 'WAIT', 'FAILED', '状态 / 分数', '追高风险', 'Gap', '5m / 15m / 30m', '距 VWAP', '成交量≈', '相对大盘', 'temporaryTrend'],
  holdings: ['总资产', '现金', '持仓市值', '总仓位', '现价', '数量（股）', '平均成本', '市值', '仓位', '盈亏'],
  quant: ['最终得分', '横截面', '时间序列', '风险扣分', '预测收益', '3D收益', '5D收益', '至今收益', '信号', '市场得分', '目标权重', 'dailyRankIcMean', 'dailyRankIcMeanStd', 'rocAuc', 'rocAucStd', 'trend_ma20', 'max_drawdown_60d', 'Embargo'],
  quantDataset: ['状态', '股票数量', '数据行数', '价格模式'],
  crypto: ['marketRegime', 'action', '形态', '策略状态', 'EMA20 · 1h', '量比 · 15m', 'totalReturn', 'annualized', 'winRate', '当前 BTC 浮盈率'],
  confluence: ['strongConfluence', 'ignitionTopIndustry', 'confluence', 'signals', 'lifecycleFragility', 'quantRank', 'etfRank'],
  'confluence-trend': ['trendQuality', 'state', 'fragilityScore'],
  flow: ['上榜股票', '买入额', '卖出额', '所选口径净额', '机构净额', '游资净额', 'Top5正流入占比', '所选概念贡献', '已采集日净额', '样本净额', '股票整体净额', '所选口径原始净额'],
  sentiment: ['涨停参与度', '首板', '连板接力', '最高连续板', '热度', '情绪状态', '早封率', '封单留存中位数'],
  watch: ['最新价', '今日涨跌幅', '趋势持续', '最近形态', '日内方向状态', '开盘', '最高', '最低', '昨收', '成交量 (Volume)'],
  industry: ['综合强度', '状态', '收盘价', 'MA5', 'MA20', '行业覆盖', '5 日动量变化（百分点）', '1 日排名变化（名）', '上涨占比（%）', 'MA5（%）', 'MA20（%）', '最新价'],
  study: ['N', '覆盖率', '5D 胜率', '10D 平均超额', 'MFE20', 'MAE20', '可评价 N', '缺行情', '超额胜率'],
};

describe('source-specific metric hint coverage', () => {
  for (const [scope, labels] of Object.entries(required)) {
    it(`has substantive help for ${scope} KPI and metric headers`, () => {
      for (const label of labels) {
        const hint = metricHint(scope, label);
        expect(hint, `${scope}/${label}`).toBeDefined();
        expect(hint!.length, `${scope}/${label}`).toBeGreaterThan(20);
        expect(hint).not.toBe(label);
      }
    });
  }
  it('does not confuse identically named market scores and states', () => {
    expect(metricHint('macro', 'macroRegime')).toContain('<35');
    expect(metricHint('trend', 'marketRegime')).toContain('< 40');
    expect(metricHint('quant', '市场状态')).toContain('≤0.35');
    expect(metricHint('quantDataset', '状态')).toContain('building');
    expect(metricHint('quantModel', '状态')).toContain('production');
    expect(metricHint(undefined, '状态')).toBeUndefined();
  });
  it('lists complete small enums and preserves unit / missing-data distinctions', () => {
    for (const value of ['IDLE', 'WATCHING', 'CANDIDATE', 'TRENDING', 'WEAKENING', 'BROKEN']) expect(trend.state).toContain(value);
    for (const value of ['NONE', 'BOX_FORMING', 'BOX_READY', 'BOX_BREAKOUT']) expect(trend.boxState).toContain(value);
    for (const value of ['MR_NONE', 'MR_OVERSOLD', 'MR_REBOUND']) expect(trend.mrState).toContain(value);
    for (const value of ['BUY', 'HOLD', 'EXIT', 'WATCH']) expect(etf.action).toContain(value);
    expect(trend.dataCoverage).toContain('90%');
    expect(trend.trendAcceleration).toContain('无0–100');
    expect(metricHint('intraday', '5m / 15m / 30m')).toContain('不是最近滚动');
    expect(metricHint('holdings', '总资产')).toContain('不代表完整资产');
    expect(metricHint('quant', '预测收益')).toContain('T+1开盘');
    expect(metricHint('quant', '5D收益')).toContain('信号日收盘');
  });
});
