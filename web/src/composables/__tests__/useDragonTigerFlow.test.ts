import { describe, it, expect, vi } from 'vitest';
import { defineComponent } from 'vue';
import { mount, flushPromises } from '@vue/test-utils';
import { useDragonTigerFlow } from '../useDragonTigerFlow';
import { dragonTigerFlowApi, type FlowOverview } from '@/api/dragonTigerFlow';
import { toCamelCase } from '@/api/utils';
import raw from '../../../e2e/fixtures/dragonTigerFlow';
vi.mock('@/api/dragonTigerFlow', () => ({ dragonTigerFlowApi: { overview: vi.fn(), dates: vi.fn() } }));
const data = toCamelCase<FlowOverview>(raw);
function setupPage() {
  let page!: ReturnType<typeof useDragonTigerFlow>;
  const wrapper = mount(defineComponent({ setup() { page = useDragonTigerFlow(); return () => null; } }));
  return { page, wrapper };
}
describe('Dragon Tiger request generations', () => {
  it('ignores a stale response and keeps export/drilldown in one batch', async () => {
    let first!: (value: FlowOverview) => void;
    vi.mocked(dragonTigerFlowApi.overview).mockReturnValueOnce(new Promise(resolve => { first = resolve; }))
      .mockResolvedValueOnce({ ...data, revision: 'new', board: 'org' });
    const { page, wrapper } = setupPage();
    void page.load(); page.change({ board: 'org' });
    await flushPromises();
    expect(page.data.value?.revision).toBe('new');
    first(data); await flushPromises();
    expect(page.data.value?.revision).toBe('new');
    expect(page.data.value?.board).toBe('org');
    expect(page.stock.value).toBe('');
    wrapper.unmount();
  });
  it('clears old evidence on failure and records retryable date errors', async () => {
    vi.mocked(dragonTigerFlowApi.overview).mockRejectedValueOnce(new Error('offline'));
    vi.mocked(dragonTigerFlowApi.dates).mockRejectedValueOnce(new Error('offline'));
    const { page, wrapper } = setupPage();
    await Promise.all([page.load(), page.loadDates()]);
    expect(page.error.value).not.toBeNull(); expect(page.datesError.value).not.toBeNull();
    expect(page.data.value).toBeNull(); expect(page.loading.value).toBe(false);
    wrapper.unmount();
  });
});
