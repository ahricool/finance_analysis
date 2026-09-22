// Synthetic, deterministic fixture. No upstream payloads or credentials.
const dates = ['2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18', '2026-09-21'];
const names = ['半导体', '机器人', '算力'];
const evidence = dates.flatMap(trade_date => Array.from({ length: 16 }, (_, i) => {
  const concepts = ['半导体', i % 2 ? '机器人' : '算力'];
  const original_net_value = (8 - i) * 1e8;
  return concepts.map(name => ({
    symbol: `${600001 + i}.SH`, name: `测试股票${i + 1}`, trade_date, range_days: 1,
    concepts, concept_id: `concept-${names.indexOf(name)}`, concept_name: name, allocation_count: 2,
    original_net_value, stock_net_value: original_net_value, net_value: original_net_value / 2,
    buy_value: 6e8, sell_value: (12e8 - original_net_value) / 2,
    org_net_value: original_net_value / 10, hot_money_net_value: original_net_value * .15,
  }));
}).flat());
const concepts = names.map((name, i) => {
  const rows = evidence.filter(r => r.concept_name === name);
  const daily = rows.filter(r => r.trade_date === dates[0]).reduce((s, r) => s + r.net_value, 0);
  return { id: `concept-${i}`, name, net_value: daily * 5, org_net_value: daily,
    hot_money_net_value: daily * 1.5, stock_count: new Set(rows.map(r => r.symbol)).size,
    values: dates.map((_, j) => daily * (j + 1)) };
}).sort((a, b) => b.net_value - a.net_value);
const raw = {
  version: 'dragon-tiger-flow-v1', revision: 'fixture', board: 'all', range_days: 1,
  trade_date: dates.at(-1)!, expected_trade_date: dates.at(-1)!, dates, complete: true, missing_dates: [],
  excluded_undisclosed_count: 0,
  summary: { stock_count: 16, net_value: 4e9, buy_value: 96e9, sell_value: 92e9,
    org_net_value: 8e8, hot_money_net_value: 12e8, top5_concentration: 1 },
  concepts, evidence, hot_money_details: [],
  source_quality: dates.map(trade_date => ({ trade_date, generated_at: `${trade_date}T11:30:00Z`, errors: {}, sources: { all: {}, org: {}, hot_money: {} } })),
  attribution: 'independent_overlapping_categories', source: 'fuyao:/api/a-share/special-data/dragon-tiger-list', unit: 'CNY',
};
export default raw;
