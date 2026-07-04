import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import BacktestEngineSelector from '../BacktestEngineSelector.vue';
import type { BacktestEngine } from '@/types/backtests';

const engines: BacktestEngine[] = [
  { key: 'backtrader', name: 'Backtrader', description: '默认引擎', displayOrder: 1, isDefault: true, recommended: true, available: true, unavailableReason: null, version: '1.9.78.123', supportedMarkets: ['US', 'CN'], supportedStrategies: ['sma_cross'] },
  { key: 'rqalpha', name: 'RQAlpha', description: '第二引擎', displayOrder: 2, isDefault: false, recommended: false, available: true, unavailableReason: null, version: '6.2.0', supportedMarkets: ['CN'], supportedStrategies: ['sma_cross'] },
  { key: 'rqalpha', name: '不可用引擎', description: 'disabled', displayOrder: 3, isDefault: false, recommended: false, available: false, unavailableReason: 'Python import failed', version: null, supportedMarkets: [], supportedStrategies: [] },
];

describe('BacktestEngineSelector', () => {
  it('shows Backtrader first with default/recommended badges and allows RQAlpha selection', async () => {
    const wrapper = mount(BacktestEngineSelector, { props: { engines, modelValue: 'backtrader' } });
    const buttons = wrapper.findAll('button');
    expect(buttons[0].text()).toContain('Backtrader');
    expect(buttons[0].text()).toContain('推荐');
    expect(buttons[0].text()).toContain('默认');
    await buttons[1].trigger('click');
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['rqalpha']);
    expect(buttons[2].attributes('disabled')).toBeDefined();
    expect(buttons[2].text()).toContain('Python import failed');
  });
});
