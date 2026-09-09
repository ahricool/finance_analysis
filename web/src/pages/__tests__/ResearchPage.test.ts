import { mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it } from 'vitest';
import ResearchPage from '../ResearchPage.vue';

async function mountResearch(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/research/quant', component: { template: '<div>量化内容</div>' } },
      { path: '/research/etf-rotation', component: { template: '<div>ETF 轮动内容</div>' } },
      { path: '/research/trend-following', component: { template: '<div>趋势跟踪内容</div>' } },
      { path: '/research/crypto/btc', component: { template: '<div>BTC 内容</div>' } },
    ],
  });
  await router.push(path);
  await router.isReady();
  return mount(ResearchPage, { global: { plugins: [router] } });
}

describe('ResearchPage', () => {
  it('renders every research destination with the current tab selected', async () => {
    const wrapper = await mountResearch('/research/etf-rotation');

    expect(wrapper.get('[data-testid="module-tabs"]').attributes('aria-label')).toBe(
      '研究页面导航',
    );
    expect(wrapper.findAll('a[href="/research/quant"]')).toHaveLength(1);
    const rotationLinks = wrapper.findAll('a[href="/research/etf-rotation"]');
    expect(rotationLinks).toHaveLength(1);
    expect(rotationLinks[0]?.attributes('data-state')).toBe('active');
    expect(wrapper.findAll('a[href="/research/trend-following"]')).toHaveLength(1);
    expect(wrapper.findAll('a[href="/research/crypto/btc"]')).toHaveLength(1);
    expect(wrapper.text()).toContain('ETF 轮动内容');
  });
});
