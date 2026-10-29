import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import type { ConfluenceItem, ConfluenceRanking } from '@/api/confluence';
import { toCamelCase } from '@/api/utils';
import raw from '../../../../e2e/fixtures/confluenceV2';
import legacy from '../../../../e2e/fixtures/confluence';
import adapted from '../../../../e2e/fixtures/confluenceV21';
import Evidence from '../ConfluenceEvidence.vue';
import { agreement, strength } from '../evidence';

describe('confluence evidence', () => {
  it('renders eight families and the complete period/style matrix with missing cells', () => {
    const row = toCamelCase<ConfluenceRanking>(raw).items[0]!;
    const wrapper = mount(Evidence, { props: { row } });
    expect(wrapper.findAll('article')).toHaveLength(8);
    expect(wrapper.get('[data-testid="evidence-options"]').text()).toContain('缺失');
    expect(wrapper.get('[data-testid="evidence-etf"]').text()).toContain('半导体ETF');
    const matrix = wrapper.get('[data-testid="evidence-trend"]');
    for (const value of ['20D', '40D', '60D', '趋势', '突破', '超跌反弹', '—', '0.0']) expect(matrix.text()).toContain(value);
    expect(agreement(row)).toBe('4/4');
    wrapper.unmount();
  });
  it('preserves historical raw weights and never invents missing new signals', () => {
    const row = toCamelCase<{ items: ConfluenceItem[] }>(legacy).items[0]!;
    expect(strength(row, 'industry')).toBe(100);
    expect(strength(row, 'macro')).toBeNull();
    expect(strength(row, 'options')).toBeNull();
  });
  it('separates overall risk from industry fit and explains each signed contribution', () => {
    const row = toCamelCase<ConfluenceRanking>(adapted).items[0]!;
    const wrapper = mount(Evidence, { props: { row } });
    const card = wrapper.get('[data-testid="evidence-macro"]');
    for (const text of ['宏观适配', '整体风险偏好', '80', '行业适配度', '74', 'A股成长风格', '敏感系数', '+0.8', '+24.00']) expect(card.text()).toContain(text);
    wrapper.unmount();
  });
  it('shows background and missing cause without inventing an adaptation score', () => {
    const row = toCamelCase<ConfluenceRanking>(adapted).items[0]!;
    row.signals.macro = { ...row.signals.macro, status: 'unavailable', strength: null, score: null, contribution: null, normalizedWeight: null,
      evidence: { ...row.signals.macro.evidence, adaptationScore: null, profiles: [], adaptationReason: '无目标日期可用行业分类，宏观适配留空' } };
    const wrapper = mount(Evidence, { props: { row } });
    const card = wrapper.get('[data-testid="evidence-macro"]');
    expect(card.text()).toContain('整体风险偏好');
    expect(card.text()).toContain('80');
    expect(card.text()).toContain('宏观适配留空');
    expect(strength(row, 'macro')).toBeNull();
    wrapper.unmount();
  });

});
