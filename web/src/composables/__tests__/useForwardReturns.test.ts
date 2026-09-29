import { mount, flushPromises } from '@vue/test-utils';
import { defineComponent, ref } from 'vue';
import { it, expect, vi } from 'vitest';
import { marketDataApi } from '@/api/marketData';
import { useForwardReturns } from '../useForwardReturns';

vi.mock('@/api/marketData', () => ({ marketDataApi: { forwardReturns: vi.fn() } }));

it('discards old-date results and clears official values when switching to preview', async () => {
  let resolve!: (value: { items: [] }) => void;
  vi.mocked(marketDataApi.forwardReturns).mockReturnValueOnce(new Promise(r => { resolve = r; }))
    .mockResolvedValueOnce({ items: [{ code: 'AAPL.US', forwardReturn3D: .1, forwardReturn5D: null, forwardReturn10D: -.2 }] });
  const day = ref('2026-09-18');
  const mode = ref('official');
  let result!: ReturnType<typeof useForwardReturns>;
  const wrapper = mount(defineComponent({ setup() {
    result = useForwardReturns(ref([{ code: 'AAPL.US' }]), ref('US'), () => day.value, mode);
    return () => null;
  } }));
  const signal = vi.mocked(marketDataApi.forwardReturns).mock.calls[0]![3]!;
  day.value = '2026-09-21';
  await flushPromises();
  expect(signal.aborted).toBe(true);
  expect(result.value('AAPL.US', 'forwardReturn3D')).toBe(.1);
  resolve({ items: [] });
  await flushPromises();
  expect(result.value('AAPL.US', 'forwardReturn3D')).toBe(.1);
  mode.value = 'preview';
  await flushPromises();
  expect(result.value('AAPL.US', 'forwardReturn3D')).toBeNull();
  expect(marketDataApi.forwardReturns).toHaveBeenCalledTimes(2);
  wrapper.unmount();
});
