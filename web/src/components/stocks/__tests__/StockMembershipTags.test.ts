import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { stocksApi } from '@/api/stocks';
import StockMembershipTags from '../StockMembershipTags.vue';

vi.mock('@/api/stocks', () => ({ stocksApi: { classification: vi.fn() } }));

describe('StockMembershipTags', () => {
  beforeEach(() => vi.resetAllMocks());

  it.each([
    { names: ['沪深300'] },
    { names: ['S&P 500', 'Nasdaq 100'] },
    { names: [] },
  ])('shows current index names for $names', async ({ names }) => {
    vi.mocked(stocksApi.classification).mockResolvedValue({
      code: 'NVDA.US', market: 'US',
      memberships: { indices: names.map(name => ({ key: name, name, source: 'WIKIPEDIA' })) },
    });
    const wrapper = mount(StockMembershipTags, { props: { code: 'NVDA.US' } });
    expect(wrapper.find('[data-testid="stock-membership-tags"]').exists()).toBe(false);
    await flushPromises();
    expect(wrapper.find('[data-testid="stock-membership-tags"]').exists()).toBe(names.length > 0);
    names.forEach(name => expect(wrapper.text()).toContain(name));
    expect(stocksApi.classification).toHaveBeenCalledWith('NVDA.US', expect.any(AbortSignal));
    wrapper.unmount();
  });

  it('hides the region when the request fails', async () => {
    vi.mocked(stocksApi.classification).mockRejectedValue(new Error('offline'));
    const wrapper = mount(StockMembershipTags, { props: { code: 'NVDA.US' } });
    await flushPromises();
    expect(wrapper.find('[data-testid="stock-membership-tags"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
