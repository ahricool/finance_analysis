import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import BilingualLabel from '../BilingualLabel.vue';
import BilingualEnum from '../BilingualEnum.vue';

describe('BilingualLabel', () => {
  it('renders Chinese primary and English subtitle from glossary key', () => {
    const wrapper = mount(BilingualLabel, { props: { label: 'marketRegime' } });
    expect(wrapper.text()).toContain('市场环境');
    expect(wrapper.text()).toContain('Market Regime');
  });

  it('hides English subtitle in compact mode but keeps it accessible', () => {
    const wrapper = mount(BilingualLabel, { props: { label: 'universeSize', compact: true } });
    expect(wrapper.text()).toContain('股票池规模');
    expect(wrapper.text()).not.toContain('Universe Size');
    expect(wrapper.attributes('title')).toBeUndefined();
    expect(wrapper.attributes('aria-label')).toBe('股票池规模（Universe Size）');
  });
});

describe('BilingualEnum', () => {
  it('maps API enums to Chinese primary without changing the English code', () => {
    const wrapper = mount(BilingualEnum, { props: { value: 'RISK_OFF', size: 'large' } });
    expect(wrapper.text()).toContain('风险规避');
    expect(wrapper.text()).toContain('RISK_OFF');
  });

  it('uses compact Chinese-only inside badge/chip size with accessible English', () => {
    const wrapper = mount(BilingualEnum, { props: { value: 'HOLD', size: 'badge' } });
    expect(wrapper.text()).toContain('持有');
    expect(wrapper.text()).not.toContain('HOLD');
    expect(wrapper.attributes('title')).toBeUndefined();
    expect(wrapper.attributes('aria-label')).toBe('持有（HOLD）');
  });
});
