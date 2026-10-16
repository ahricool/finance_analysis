import type { MacroSeriesResult } from '@/api/macro';

/** Align on stored market sessions, so weekends/holidays never create false gaps. */
export function alignMacroSeries(result: MacroSeriesResult | null) {
  const dates = [...new Set([
    ...(result?.dates ?? []),
    ...(result?.series.flatMap(series => series.points.map(point => point.date)) ?? []),
  ])].sort();
  return {
    dates,
    series: (result?.series ?? []).map(series => {
      const points = new Map(series.points.map(point => [point.date, point.value]));
      const values = dates.map(date => points.get(date) ?? null);
      const first = values.findIndex(value => value !== null);
      const last = values.length - 1 - [...values].reverse().findIndex(value => value !== null);
      return { ...series, values, hasGap: first >= 0 && values.slice(first, last + 1).includes(null) };
    }),
  };
}
