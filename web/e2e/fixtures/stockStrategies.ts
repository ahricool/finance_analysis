export const strategy = {
  key: 'ma_dd30', version: '1', name: '均线20/50／1仓／DD30暂停7日／ATR0', markets: ['US'], family: 'ma', slots: 1,
  atr: 0, account_dd: .3, cooldown: 7, risk_engine: '20261021', breadth: false, breakout: false, source_id: 'US_local_f20_s50_long_n1_a0_dd0.3_c7',
  rules: [{ label: '入场与排序', text: '收盘>MA20>MA50、收盘>MA200且126日收益>0，按MA20/MA50−1降序。' },
    { label: '账户回撤与恢复', text: '账户回撤严格超过30%，下一开盘清仓，暂停7个开盘。' },
    { label: '数据适配', text: '冻结已同步股票与ETF池；美股广度使用标普500成分。' }],
};
export const day = {
  trade_date: '2026-10-19', nav: 1100000, daily_return: .01, total_return: .1, cagr: .2,
  max_drawdown: -.05, drawdown: -.02, exposure: 1, benchmark_return: .05, created_at: '2026-10-20T02:00:00Z',
  payload: {
    cash: 0, positions: { 'AAPL.US': { name: '苹果', quantity: 5000, entry_price: 200, mark: 220, mark_date: '2026-10-19', peak: 230, stop: null, pending_exit: [] } },
    fills: [{ code: 'AAPL.US', name: '苹果', action: 'BUY', quantity: 5000, price: 200, amount: 1000000, pnl: null, reasons: ['上一交易日候选'], signal_date: '2026-10-16' }],
    adjustments: [], blocked: [], warnings: [], stale_codes: [], sessions: 30, closed_rounds: 2, win_rate: .5, annual_turnover: 3,
    pause_remaining: 0, breadth: null, breadth_denominator: null, provenance: { window_start: '2025-05-01', window_end: '2026-10-19' },
    computed_at: '2026-10-20T02:00:00Z', replayed: false, next_is_historical: false,
    plan: { signal_date: '2026-10-19', execution_date: '2026-10-20', status: 'READY',
      candidates: [{ code: 'AAPL.US', name: '苹果', score: .3, atr: 3, type: 'STOCK', signal_close: 220 }], exits: { 'AAPL.US': [] } },
  },
};
export const lastRun = { trade_date: '2026-10-20', status: 'failed', reason: '测试失败原因：缺少必要市场数据', attempts: 2, updated_at: '2026-10-21T02:00:00Z' };
export const overview = { market: 'US', items: [{ strategy, latest: day, last_run: lastRun, start_date: '2026-09-01', status: 'failed' }] };
export const detail = { market: 'US', strategy, latest: day, last_run: lastRun, start_date: '2026-09-01',
  universe: { stocks: ['AAPL.US'], etfs: ['SPY.US'], breadth: ['AAPL.US'], hash: 'test-frozen-hash' },
  curve: [
    { ...day, trade_date: '2026-10-15', total_return: 0, drawdown: 0, benchmark_return: 0 },
    { ...day, trade_date: '2026-10-16', total_return: .08, drawdown: -.01, benchmark_return: .03 }, day,
  ], days: [day], next_before: null,
};
