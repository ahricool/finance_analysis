import { describe, expect, it } from 'vitest';
import { trendIndicatorDescriptions as descriptions, trendPeriodText } from '../indicatorDescriptions';

describe('strategy period descriptions', () => {
  it('scales formula windows while preserving scoring constants', () => {
    expect(trendPeriodText(descriptions.trend!, 10)).toContain('Q(R5,0.12)+0.4×Q(R10,0.18)');
    expect(trendPeriodText(descriptions.candidate!, 40)).toContain('Slope40>0');
    expect(trendPeriodText(descriptions.marketScore!, 10)).toContain('High5Count−Low5Count');
    expect(trendPeriodText(descriptions.breakout!, 40)).toContain('B(z20),B(z40)');
    expect(trendPeriodText(descriptions.atr!, 10)).toContain('Mean(TR, 10)');
    expect(trendPeriodText(descriptions.concentration!, 10)).toContain('最近5日最大的1笔');
    expect(trendPeriodText(descriptions.fragility!, 10)).toContain('1/2个交易日');
    expect(trendPeriodText(descriptions.weightedSlope!, 40)).toContain('1,2,…,40');
  });
});
