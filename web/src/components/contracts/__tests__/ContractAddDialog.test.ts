import { mount, flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ContractAddDialog from '../ContractAddDialog.vue';
import type { Contract } from '@/api/contracts';

const mocks = vi.hoisted(() => ({ search: vi.fn() }));
vi.mock('@/api/contracts', () => ({ contractsApi: mocks }));
const btc: Contract = { symbol: 'BTCUSDT', category: 'COIN', underlying_symbol: 'BTC.CRYPTO' };
const eth: Contract = { symbol: 'ETHUSDT', category: 'COIN', underlying_symbol: 'ETH.CRYPTO' };
const slot = { template: '<div><slot /></div>' };
function render() {
  return mount(ContractAddDialog, { props: { open: true, existing: [], busy: false, addError: null },
    global: { stubs: { Dialog: { props: ['open'], template: '<div v-if="open"><slot /></div>' }, DialogContent: slot, DialogHeader: slot, DialogTitle: slot, DialogDescription: slot } } });
}
beforeEach(() => { vi.useFakeTimers(); mocks.search.mockReset(); });
afterEach(() => vi.useRealTimers());

describe('contract add dialog', () => {
  it('debounces search, ignores out-of-order results, and marks an added contract', async () => {
    let resolveBTC!: (items: Contract[]) => void;
    mocks.search.mockImplementationOnce(() => new Promise(resolve => { resolveBTC = resolve; })).mockResolvedValueOnce([eth]);
    const dialog = render();
    await dialog.get('input').setValue('BTC');
    await vi.advanceTimersByTimeAsync(300);
    expect(mocks.search).toHaveBeenCalledWith('BTC', expect.any(AbortSignal));
    const first = mocks.search.mock.calls[0]![1] as AbortSignal;
    await dialog.get('input').setValue('ETH');
    expect(first.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    resolveBTC([btc]);
    await flushPromises();
    expect(dialog.find('button[aria-label="BTCUSDT · 添加"]').exists()).toBe(false);
    await dialog.get('button[aria-label="ETHUSDT · 添加"]').trigger('click');
    expect(dialog.emitted('add')).toEqual([[eth]]);
    await dialog.setProps({ existing: ['ETHUSDT'] });
    expect(dialog.get('button[aria-label="ETHUSDT 已添加"]').attributes('disabled')).toBeDefined();
    dialog.unmount();
  });
  it('discards pending search on close and reopens with an empty search', async () => {
    let resolve!: (items: Contract[]) => void;
    mocks.search.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const dialog = render();
    await dialog.get('input').setValue('BTC');
    await vi.advanceTimersByTimeAsync(300);
    await dialog.setProps({ open: false });
    resolve([btc]);
    await flushPromises();
    await dialog.setProps({ open: true });
    expect(dialog.get('input').element.value).toBe('');
    expect(dialog.find('button[aria-label="BTCUSDT · 添加"]').exists()).toBe(false);
    dialog.unmount();
  });
});
