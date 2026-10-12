// Sources: signal_center/{prompt,evaluation}.py and SignalEvaluation.vue.
const returns = '以信号实际完成后的首个可用交易日开盘（前复权）为模拟基准，第1日指该日收盘；按交易日历定位目标日，缺行情不补零、不顺延替代。未计费用、滑点、涨跌停和实际成交限制，不是账户真实收益。';
export const signalHints: Record<string, string> = {
  decision: 'BUY表示本市场当日选择一只候选股票作为研究信号；NO_TRADE表示当日不交易。没有完成分析时不产生这两种正式结论。决策是固定输入证据上的模型判断，不会自动下单。',
  confidence: '模型输出的主观信心等级：high（高）、medium（中）、low（低）。没有统计校准为具体胜率，不应把“高”理解为高收益保证。',
  '最大有利变动': `已观察前10个交易日中，最高价÷模拟基准价−1的最大值，最低为0，表示期间最大向上幅度。缺失区间行情时不计算。${returns}`,
  '最大不利变动': `已观察前10个交易日中，最低价÷模拟基准价−1的最小值，最高为0，表示期间最大向下幅度。缺失区间行情时不计算。${returns}`,
  '收盘最大回撤': `从模拟基准及随后每日收盘形成的历史高点，计算收盘价÷此前最高值−1的最小值，以负百分比显示。只看收盘，不等于盘中最大不利变动。${returns}`,
  '收益回看': '评估状态：pending（等待首日收盘）、partial（持续观察）、complete（10日观察完成）、unavailable（不可评估）、not_applicable（不适用，如NO_TRADE）。单个期限结果也可能为pending（未到期）或missing（缺行情），不是0收益。',
};
for (const days of [1, 3, 5, 10]) {
  const hint = `第${days}个交易日收盘价÷模拟基准开盘价−1，以百分比显示。${returns}`;
  signalHints[`${days}D 收益`] = hint;
  signalHints[`${days}D`] = hint;
}
