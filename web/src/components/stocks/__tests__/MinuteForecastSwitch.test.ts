import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MinuteForecastSwitch from '../detail/MinuteForecastSwitch.vue';
import { fetchMinuteForecastPreference, saveMinuteForecastPreference } from '@/api/minuteForecast';

vi.mock('@/api/minuteForecast', () => ({
  fetchMinuteForecastPreference: vi.fn(),
  saveMinuteForecastPreference: vi.fn(),
}));
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ currentUser: { role: 'admin' } }) }));

describe('shared minute forecast switch', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(fetchMinuteForecastPreference).mockResolvedValue({ enabled: false });
  });
  it('reads default off, persists enable and disable without optimistic state', async () => {
    const wrapper = mount(MinuteForecastSwitch, { props: { symbol: 'AAPL.US' } });
    await flushPromises();
    const control = () => wrapper.get('[role="switch"]');
    expect(control().attributes('aria-checked')).toBe('false');
    let finish!: (value: { enabled: boolean }) => void;
    vi.mocked(saveMinuteForecastPreference).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    await control().trigger('click');
    expect(saveMinuteForecastPreference).toHaveBeenCalledWith('AAPL.US', true, false);
    expect(control().attributes('aria-checked')).toBe('false');
    expect(control().attributes('disabled')).toBeDefined();
    finish({ enabled: true }); await flushPromises();
    expect(control().attributes('aria-checked')).toBe('true');
    vi.mocked(saveMinuteForecastPreference).mockResolvedValueOnce({ enabled: false });
    await control().trigger('click'); await flushPromises();
    expect(saveMinuteForecastPreference).toHaveBeenLastCalledWith('AAPL.US', false, false);
    expect(control().attributes('aria-checked')).toBe('false');
    wrapper.unmount();
  });
  it('ignores a late response for a previously displayed stock', async () => {
    let finish!: (value: { enabled: boolean }) => void;
    vi.mocked(fetchMinuteForecastPreference).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = mount(MinuteForecastSwitch, { props: { symbol: 'AAPL.US' } });
    await wrapper.setProps({ symbol: '600519.SH' });
    await flushPromises();
    finish({ enabled: true }); await flushPromises();
    expect(wrapper.get('[role="switch"]').attributes('aria-checked')).toBe('false');
    wrapper.unmount();
  });
});
