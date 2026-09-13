/** Public API responses shared by Dashboard component and browser tests. */
export function dashboardResponse(url: URL): object {
  const market = url.searchParams.get('market') ?? 'CN';
  const name = market === 'CN' ? '中际旭创' : 'NVIDIA';
  const code = market === 'CN' ? '300308.SZ' : 'NVDA.US';
  const current = { code, name, action: 'ENTRY', state: 'ENTRY' };
  const change = { current, previousAction: 'WATCH', previousState: 'CANDIDATE' };
  const path = url.pathname;
  if (url.pathname === '/api/v1/market-structure') return {
    market: url.searchParams.get('market') || 'CN', trade_date: '2026-09-08', expected_trade_date: '2026-09-08',
    breadth: { breadth_divergence_5d: 0.028, benchmark_return_5d: 0.035, median_member_return_5d: 0.007,
      member_positive_ratio_5d: 0.6, member_above_ma10_ratio: 0.7, member_above_ma20_ratio: 0.75 },
    rotation: { rotation_velocity_1d: 20, rotation_velocity_3d: 76, rotation_velocity_5d: null },
    leadership: { leadership_concentration_1d: 0.6, leadership_concentration_5d: 0.68, leadership_hhi_5d: 12 },
    metrics: { states: { breadth: 'STRONG_DIVERGENCE', rotation: 'EXTREME' }, universe_key: 'cn_daily_sync',
      member_count: 800, universe_size: 800, data_coverage: 1, benchmark_code: '510300.SH' },
  };
  if (path === '/api/v1/auth/status') return { loggedIn: true, user: { uid: 1, username: 'Reviewer', role: 'user', extra: {} } };
  if (path === '/api/v1/quant/market-regime/latest') return {
    market, trade_date: '2026-09-09', regime: market === 'CN' ? 'risk_on' : 'neutral', market_score: market === 'CN' ? 0.724 : 0.532, max_equity_exposure: market === 'CN' ? 0.7 : 0.5,
  };
  if (path === '/api/v1/quant/signals/ranking') return {
    market, trade_date: '2026-09-09', items: [name, market === 'CN' ? '北方华创' : 'Broadcom', market === 'CN' ? '立讯精密' : 'Micron'].map((name, i) => ({ code: `${code}-${i}`, name, final_score: 87.4 - i * 3.2 })),
  };
  if (path === '/api/v1/etf-rotation/ranking') return {
    market, trade_date: '2026-09-09', market_snapshot: { regime: 'RISK_ON' }, items: [],
    changes: { previous_trade_date: '2026-09-08', new_buys: [{ ...change, previousAction: 'HOLD', current: { code: 'ETF1', name: market === 'CN' ? '半导体 ETF' : 'Semiconductor ETF', action: 'BUY' } }], new_exits: [{ ...change, current: { code: 'ETF2', name: market === 'CN' ? '银行 ETF' : 'Bank ETF', action: 'EXIT' } }], rank_movers: [change, change] },
  };
  if (path === '/api/v1/trend-following/ranking') return {
    market, trade_date: '2026-09-09', market_regime: 'RISK_ON', items: [],
    features: { lifecycle_counts: { IGNITION: 12, EMERGING: 35, EXPANSION: 64, MATURE: 81, EXHAUSTION: 17, BROKEN: 40 }, high_fragility_count: 23 },
    changes: { previous_trade_date: '2026-09-08', transitions: [change, { ...change, current: { code: 'watch', name: 'Ordinary Watch', state: 'WATCHING', action: 'WATCH' } }, { ...change, previousState: 'HOLDING', previousAction: 'HOLD', current: { code: 'weak', name: market === 'CN' ? '贵州茅台' : 'Apple', action: 'STOP_ADD', state: 'WEAKENING' } }] },
  };
  if (path === '/api/v1/crypto/btc/overview') return {
    symbol: 'BTCUSDT', strategy: { regime: 'BULL', setup: 'BREAKOUT', action: 'BUY', position_state: 'LONG', price: '114820' },
    market: { last_update_time: '2026-09-09T08:00:00Z', latest_candle: { close: '114820' } },
  };
  if (path === '/api/v1/timeline') {
    const base = { market: 'US', related_symbols: [], importance: 'high', impact: null, importance_score: null, detail_payload: {} };
    const items = [
      { ...base, id: 'finance_event:1', event_time: '2026-09-12T20:00:00Z', category: 'event', calendar_type: 'earnings', title: 'ORCL FY27 Q1 财报', summary: '', detail_payload: { currency: 'USD', eps_estimate: 1.36, market_session: 'amc' } },
      { ...base, id: 'finance_event:2', event_time: '2026-09-10T12:30:00Z', category: 'event', calendar_type: 'macro', title: '美国消费者价格指数 CPI', summary: '关注核心通胀与利率预期', importance: 'critical' },
      { ...base, id: 'news:1', event_time: '2026-09-09T07:50:00Z', category: 'news', title: 'NVIDIA 上调 AI Server 需求预期', summary: '数据中心订单增长，关注资本开支与产能交付', related_symbols: ['NVDA', 'AMD'], importance_score: 9, impact: 'bullish' },
      { ...base, id: 'report:1', event_time: '2026-09-09T07:30:00Z', category: 'analysis', title: '科技板块继续强于大盘', summary: '市场方向仍待成交确认，复核关键价位与开盘量能' },
      { ...base, id: 'news:2', event_time: '2026-09-09T06:30:00Z', category: 'news', title: '美债收益率回落，成长股估值迎来修复', summary: '关注后续经济数据对风险偏好的影响', related_symbols: ['TLT'], impact: 'bullish' },
      { ...base, id: 'report:2', event_time: '2026-09-09T05:00:00Z', category: 'analysis', market: 'CN', title: 'A股午后观察：成交集中于科技主线', summary: '板块持续性仍需确认，避免短期追高' },
      { ...base, id: 'news:3', event_time: '2026-09-08T20:00:00Z', category: 'news', title: '半导体供应链展望上调', summary: '新增订单反映需求韧性，关注存储价格变化' },
      { ...base, id: 'news:4', event_time: '2026-09-08T18:00:00Z', category: 'news', title: '能源板块承压，原油需求预期走弱', summary: '周期板块相对表现回落', impact: 'bearish' },
    ];
    return { items: url.searchParams.get('category') === 'event' ? items.filter(item => item.category === 'event') : items, total: items.length, next_cursor: null, has_more: false, limit: 10 };
  }
  throw new Error(`Unexpected Dashboard request: ${path}`);
}
