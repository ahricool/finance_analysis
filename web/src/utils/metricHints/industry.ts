// Sources: industry_strength/{features,state,service}.py and UI display.ts.
import { rankingColumns } from '@/components/industry-strength/display';
export const industryHints: Record<string, string> = {
  '行业覆盖': '本次参与排名的有效行业数/目录应覆盖行业数。不是成分股票行情覆盖率；排名与强度分位都只在本次有效行业截面中计算。',
  '快照': '正式收盘是已保存的日度结果；盘中预览是临时结果，收盘前可能变化。查看历史行业日期不会把下方最新成分股数据回溯到同一天。',
  '数据有效日期': '当前行业快照所描述的交易日；生成/更新时间是计算时间，两者可能不同。',
  '收盘价': '成分数据物化时使用的最新日线收盘价，单位人民币；不随上方行业历史日期切换，不是实时盘口价。',
  '涨跌幅（%）': '正式成分记录为日线收盘相对前一交易日涨跌幅；盘中预览为当前报价相对前收的涨跌幅，按百分比展示，收盘前会变化。缺少基准时不可用。',
  'MA5': '正式记录表示收盘是否高于5日均线，盘中预览按当前报价覆盖当日临时日线后计算。是为高于，否为未高于，—为无法判断；这里是布尔状态，不是均线价格。',
  'MA20': '正式记录表示收盘是否高于20日均线，盘中预览按当前报价覆盖临时日线后计算。取值是/否/未知（—）；数据不足不能解释成均线下方。',
  '成交额': '正式记录为所用交易日成交金额；盘中预览为报价提供的当日累计成交额，尚未收盘。单位人民币，页面按亿元显示；不是资金净流入或市值。',
};
for (const column of rankingColumns) {
  industryHints[column.label] = column.hint;
  industryHints[column.short] = column.hint;
}
for (const days of [5, 10, 20]) {
  industryHints[`${days} 日收益（%）`] = `行业指数最近${days}个交易日收盘价变化：当前收盘÷${days}日前收盘−1。页面数值单位为%，不是收益金额。`;
  industryHints[`${days} 日超额（百分点）`] = `行业指数${days}日收益−同期沪深300收益，页面数值单位为百分点。正值为跑赢基准，负值为跑输。`;
}
for (const column of rankingColumns) {
  if (column.unit) {
    industryHints[`${column.label}（${column.unit}）`] = column.hint;
    industryHints[`${column.short}（${column.unit}）`] = column.hint;
  }
}
industryHints['MA5（%）'] = industryHints['站上 MA5 的成分股占比']!;
industryHints['MA20（%）'] = industryHints['站上 MA20 的成分股占比']!;
industryHints['最新价'] = '盘中预览成分记录使用的最新可用报价，单位人民币；以该批数据的观测时间为准，收盘前会变化。它不是上方历史行业日期的收盘价。';
