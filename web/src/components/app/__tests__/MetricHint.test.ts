import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, describe, expect, it } from 'vitest';
import { nextTick } from 'vue';
import MetricHint from '../MetricHint.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import IndicatorHelpLabel from '../IndicatorHelpLabel.vue';

const cleanups: Array<() => void> = [];
afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); document.body.innerHTML = ''; });
function hint() {
  const wrapper = mount(MetricHint, { attachTo: document.body, props: { label: '测试指标', description: '说明包含范围、单位和缺失口径。' } });
  cleanups.push(() => wrapper.unmount());
  return wrapper;
}

describe('MetricHint', () => {
  it('opens on keyboard focus and Escape closes only this help', async () => {
    const wrapper = hint();
    wrapper.get('button').element.focus();
    await nextTick();
    expect(wrapper.get('button').attributes('aria-expanded')).toBe('true');
    expect(document.body.textContent).toContain('说明包含范围');
    await wrapper.get('button').trigger('keydown', { key: 'Escape' });
    expect(wrapper.get('button').attributes('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(wrapper.get('button').element);
  });

  it.each(['mouse', 'touch'])('supports %s click/tap and repeated interaction to dismiss', async pointerType => {
    const wrapper = hint();
    await wrapper.get('button').trigger('click');
    expect(wrapper.get('button').attributes('aria-expanded')).toBe('true');
    await new Promise(resolve => setTimeout(resolve, 0));
    await wrapper.get('button').trigger('pointerdown', { pointerType });
    await flushPromises();
    await wrapper.get('button').trigger('click');
    expect(wrapper.get('button').attributes('aria-expanded')).toBe('false');
    await wrapper.get('button').trigger('click');
    expect(wrapper.get('button').attributes('aria-expanded')).toBe('true');
  });

  it('updates the open explanation when the displayed metric changes', async () => {
    const wrapper = hint();
    await wrapper.get('button').trigger('click');
    await wrapper.setProps({ label: '新的指标', description: '新的单位和缺失口径。' });
    expect(wrapper.get('button').attributes('aria-label')).toBe('查看 新的指标 说明');
    expect(document.body.textContent).toContain('新的单位和缺失口径');
    expect(document.body.textContent).not.toContain('说明包含范围');
  });

  it('dismisses on an outside pointer interaction', async () => {
    const wrapper = hint();
    await wrapper.get('button').trigger('click');
    await new Promise(resolve => setTimeout(resolve, 0));
    document.body.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0 }));
    await flushPromises();
    expect(wrapper.get('button').attributes('aria-expanded')).toBe('false');
  });

  it('opens on mouse hover', async () => {
    const wrapper = hint();
    await wrapper.get('button').trigger('pointerenter', { pointerType: 'mouse' });
    expect(wrapper.get('button').attributes('aria-expanded')).toBe('true');
  });

  it('keeps help separate from table sorting and stops help clicks', async () => {
    const wrapper = mount(SortableTableHeader, { props: { label: 'marketScore', description: '说明', active: true } });
    cleanups.push(() => wrapper.unmount());
    expect(wrapper.find('button button').exists()).toBe(false);
    expect(wrapper.attributes('aria-sort')).toBe('ascending');
    await wrapper.get('[data-slot="metric-hint-trigger"]').trigger('click');
    expect(wrapper.emitted('sort')).toBeUndefined();
    await wrapper.findAll('button')[0]!.trigger('click');
    expect(wrapper.emitted('sort')).toHaveLength(1);
  });

  it('resolves only explicit domain hints and preserves explicit overrides', () => {
    const wrapper = mount(IndicatorHelpLabel, { props: { label: 'riskScore', scope: 'macro' } });
    cleanups.push(() => wrapper.unmount());
    expect(wrapper.getComponent(MetricHint).props('description')).toContain('越高表示当前规则下越偏向风险偏好');
    const plain = mount(IndicatorHelpLabel, { props: { label: 'riskScore' } });
    cleanups.push(() => plain.unmount());
    expect(plain.findComponent(MetricHint).exists()).toBe(false);
    const override = mount(IndicatorHelpLabel, { props: { label: 'riskScore', scope: 'macro', description: '快照特定说明' } });
    cleanups.push(() => override.unmount());
    expect(override.getComponent(MetricHint).props('description')).toBe('快照特定说明');
  });
});
