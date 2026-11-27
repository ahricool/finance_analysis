import { mount, flushPromises } from '@vue/test-utils';
import { ref } from 'vue';
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
  const wrapper = mount({ setup() {
    result = useForwardReturns(ref([{ code: 'AAPL.US' }]), ref('US'), () => day.value, mode, () => false);
    result.visibility('AAPL.US', true);
    return () => null;
  } });
  await flushPromises();
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

it('loads only nearby symbols and fills the remaining export rows in batches', async () => {
  const read = vi.mocked(marketDataApi.forwardReturns);
  read.mockReset().mockResolvedValue({ items: [] });
  const items = ref(Array.from({ length: 125 }, (_, i) => ({ code: `S${i}.US` })));
  let result!: ReturnType<typeof useForwardReturns>;
  const wrapper = mount({ setup() {
    result = useForwardReturns(items, ref('US'), () => '2026-09-21', ref('official'), () => false);
    return () => null;
  } });
  expect(read).not.toHaveBeenCalled();
  result.visibility('S1.US', true);
  result.visibility('S2.US', true);
  await flushPromises();
  expect(read.mock.calls.map(call => call[0])).toEqual([['S1.US', 'S2.US']]);
  result.visibility('S1.US', false);
  await flushPromises();
  expect(read).toHaveBeenCalledTimes(1);
  await result.forExport(items.value);
  expect(read.mock.calls.map(call => call[0].length)).toEqual([2, 50, 50, 23]);
  wrapper.unmount();
});
