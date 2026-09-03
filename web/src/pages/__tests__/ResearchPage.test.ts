import { mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it } from 'vitest';
import ResearchPage from '../ResearchPage.vue';

async function mountResearch(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/market/quant', component: { template: '<div>量化内容</div>' } },
      { path: '/market/etf-rotation', component: { template: '<div>ETF 轮动内容</div>' } },
      { path: '/market/trend-following', component: { template: '<div>趋势跟踪内容</div>' } },
    ],
  });
  await router.push(path);
  await router.isReady();
  return mount(ResearchPage, { global: { plugins: [router] } });
}

describe('ResearchPage', () => {
  it('renders every research destination with the current tab selected', async () => {
    const wrapper = await mountResearch('/market/etf-rotation');

    expect(wrapper.get('[data-testid="module-tabs"]').attributes('aria-label')).toBe(
      '研究页面导航',
    );
    expect(wrapper.findAll('a[href="/market/quant"]')).toHaveLength(1);
    const rotationLinks = wrapper.findAll('a[href="/market/etf-rotation"]');
    expect(rotationLinks).toHaveLength(1);
    expect(rotationLinks[0]?.attributes('data-state')).toBe('active');
    expect(wrapper.findAll('a[href="/market/trend-following"]')).toHaveLength(1);
    expect(wrapper.text()).toContain('ETF 轮动内容');
  });
});
