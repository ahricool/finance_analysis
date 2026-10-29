import legacy from './confluenceV21';
const original = legacy.items[0]!;
const items = Array.from({ length: 50 }, (_, i) => ({ ...original,
  instrument_id: i + 1, code: `${600001 + i}.SH`, name: i === 0 ? '测试股票' : i < 10 ? `精选股票${i + 1}` : `观察股票${i + 1}`,
  confluence_score: i < 10 ? 84 - i * 1.5 : i === 20 ? 59.99 : 79 - (i - 10) * 2,
  eligible: i < 10, strong_confluence: i < 3,
  reasons: [i < 10 ? '已入选当日精选' : '仅供观察，未入选当日精选'],
}));
export default { ...legacy, algorithm_version: 'confluence_v2_2', total: 50,
  rules: { ...legacy.rules, minimum_score: 60, ranking_limit: 50, macro_method: 'sector_macro_v1' },
  summary: { ...legacy.summary, total: 50, eligible: 10, strong_confluence: 3, candidate_count: 73 }, items };
