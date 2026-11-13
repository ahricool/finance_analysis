import { expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import PredictionAdmin from '../PredictionAdmin.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
vi.mock('@/api/predictionMarkets', () => ({ predictionApi: {
  adminTags: vi.fn().mockResolvedValue({ items: Array.from({ length: 120 }, (_, i) => ({ tagId: String(i), slug: `slug${i}`, label: `Label ${i}`, visible: true, ruleGroup: 'other', manualVisible: null })) }),
  adminEvents: vi.fn().mockResolvedValue({ items: [], total: 0 }),
} }));
it('paginates the full tag catalog and searches across all pages', async () => {
  const wrapper = mount(PredictionAdmin); await flushPromises();
  expect(wrapper.findAll('[data-testid="prediction-admin-tag"]')).toHaveLength(50);
  await wrapper.findAll('button').find(b => b.attributes('aria-label') === '下一页')!.trigger('click');
  expect(wrapper.text()).toContain('slug50');
  wrapper.findAllComponents(FieldInput).find(c => c.props('label') === '全量官方标签搜索')!.vm.$emit('update:modelValue', 'slug119');
  await flushPromises();
  expect(wrapper.findAll('[data-testid="prediction-admin-tag"]')).toHaveLength(1);
  expect(wrapper.text()).toContain('slug119'); wrapper.unmount();
});
