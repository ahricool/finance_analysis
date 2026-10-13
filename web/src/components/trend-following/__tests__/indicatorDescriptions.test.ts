import { describe, expect, it } from 'vitest';
import { trendIndicatorDescriptions as descriptions, trendPeriodText } from '../indicatorDescriptions';

describe('strategy period descriptions', () => {
  it('scales formula windows while preserving scoring constants', () => {
    expect(trendPeriodText(descriptions.trend!, 60)).toContain('Q(R30,0.12)+0.4×Q(R60,0.18)');
    expect(trendPeriodText(descriptions.candidate!, 40)).toContain('Slope40>0');
    expect(trendPeriodText(descriptions.marketScore!, 60)).toContain('High30Count−Low30Count');
    expect(trendPeriodText(descriptions.breakout!, 40)).toContain('B(z20),B(z40)');
    expect(trendPeriodText(descriptions.atr!, 60)).toContain('Mean(TR, 60)');
    expect(trendPeriodText(descriptions.concentration!, 60)).toContain('最近30日最大的6笔');
    expect(trendPeriodText(descriptions.weightedSlope!, 40)).toContain('1,2,…,40');
  });
});
