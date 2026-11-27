import { reactive, ref, type InjectionKey, type Ref } from 'vue';

export const periods = [
  ['1y', '年'], ['1M', '月'], ['1w', '周'], ['1d', '日'],
  ['1h', '1h'], ['15m', '15min'], ['5m', '5min'], ['1m', '1min'],
] as const;
export type ChartPeriod = typeof periods[number][0];
export const tableChartPeriod = ref<ChartPeriod>('1m');
export const virtualChartHeight = 520;
export function createExpansion() {
  const state = reactive({ all: false, exceptions: new Set<string | number>() });
  return {
    expanded: (id: string | number) => state.all !== state.exceptions.has(id),
    toggle(id: string | number) {
      if (!state.exceptions.delete(id)) state.exceptions.add(id);
    },
    setAll(expanded: boolean) {
      state.all = expanded;
      state.exceptions.clear();
    },
  };
}
export const expansionKey: InjectionKey<ReturnType<typeof createExpansion>> = Symbol('instrument table');
export const rowVisibleKey: InjectionKey<Ref<boolean>> = Symbol('instrument row visibility');
