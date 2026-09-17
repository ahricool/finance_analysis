import type { IndustrySnapshot, IndustryState } from '@/api/industryStrength';

export const STATE_ORDER = ['EMERGING', 'STRONG', 'NEUTRAL', 'COOLING', 'WEAK'] as const;

export const stateLabels: Record<IndustryState, string> = {
  EMERGING: '加速崛起',
  STRONG: '持续强势',
  NEUTRAL: '中性',
  COOLING: '降温',
  WEAK: '弱势',
};

export const stateBadgeClass: Record<IndustryState, string> = {
  EMERGING: 'border-warning/30 bg-warning/10 text-warning',
  STRONG: 'border-market-up/30 bg-market-up/10 text-market-up',
  NEUTRAL: 'border-border bg-muted/60 text-muted-foreground',
  COOLING: 'border-sky-500/30 bg-sky-500/10 text-sky-800 dark:text-sky-300',
  WEAK: 'border-market-down/30 bg-market-down/10 text-market-down',
};

export const stateColorsLight: Record<IndustryState, string> = {
  EMERGING: '#c2410c',
  STRONG: '#dc2626',
  NEUTRAL: '#64748b',
  COOLING: '#0369a1',
  WEAK: '#047857',
};

export const stateColorsDark: Record<IndustryState, string> = {
  EMERGING: '#fb923c',
  STRONG: '#f87171',
  NEUTRAL: '#94a3b8',
  COOLING: '#7dd3fc',
  WEAK: '#34d399',
};

export function stateColors(theme: 'light' | 'dark'): Record<IndustryState, string> {
  return theme === 'dark' ? stateColorsDark : stateColorsLight;
}

/** Faithful to industry_strength/state.py + config.py; not a buy/sell rule. */
export const stateExplanations: Record<IndustryState, string> = {
  EMERGING:
    '判定：3 日排名提升至少 5 名，5 日超额为正，5 日动量变化为正，加速度分位不低于 75，且成交额脉冲不低于 1。描述市场环境，不是买入信号。',
  STRONG:
    '判定：综合强度不低于 75，排名处于当日有效行业前 25%，3 个交易日前综合强度也达到 75；5/10/20 日超额均为正；在有广度数据时，成分股上涨占比与站上 MA20 占比均不低于 60%。需要历史证据，启动阶段不会伪造该状态。综合强度不是买入概率。',
  NEUTRAL: '未命中加速崛起、持续强势、降温或弱势规则时的默认状态。',
  COOLING:
    '优先判定：综合强度不低于 60，且满足任一条件——5 日动量变化为负、成分股上涨占比低于 45%、或 3 日排名变化下降至少 3 名。用于提示高位动能转弱，不是卖出指令。',
  WEAK:
    '判定：综合强度不高于 25，5 日与 10 日超额均为负；在有广度数据时，成分股上涨占比与站上 MA20 占比均不高于 40%。',
};

export const methodologyLines = [
  '数据源：同花顺金融数据 API / 扶摇行业指数；成分股行情复用现有 A 股前复权日线。',
  '基准：沪深300（000300.SH）。5/10/20 日超额 = 行业指数收益 − 同期基准收益。',
  '综合强度 = 40%×5 日超额分位 + 35%×10 日超额分位 + 25%×20 日超额分位，按当日完整截面排序，1 为最强。',
  '5 日动量变化 = 近 5 日收益 − 再往前 5 日收益，单位为百分点，正值表示动量加快，负值表示动量降速，不是资金流出。',
  '成交额脉冲 = 近 5 日成交额均值 / 近 20 日成交额均值，衡量自身活跃程度，不是市值、绝对成交额或资金净流入。',
  '状态描述市场环境，不构成买卖建议；四象限辅助线不是交易阈值，与五种状态不是一一对应。',
];

export type FormatOptions = { digits?: number; unit?: boolean };

function finite(value: number | null | undefined): value is number {
  return value != null && Number.isFinite(value);
}

export function formatPercent(value: number | null | undefined, options: FormatOptions = {}): string {
  if (!finite(value)) return '—';
  const digits = options.digits ?? 1;
  const text = `${(value * 100).toFixed(digits)}`;
  return options.unit === false ? text : `${text}%`;
}

export function formatPoints(value: number | null | undefined, options: FormatOptions = {}): string {
  if (!finite(value)) return '—';
  const digits = options.digits ?? 2;
  const text = (value * 100).toFixed(digits);
  if (options.unit === false) return text;
  return `${text} 个百分点`;
}

export function formatScore(value: number | null | undefined, digits = 1): string {
  return finite(value) ? value.toFixed(digits) : '—';
}

export function formatPulse(value: number | null | undefined, options: FormatOptions = {}): string {
  if (!finite(value)) return '—';
  const text = value.toFixed(options.digits ?? 2);
  return options.unit === false ? text : `${text}×`;
}

export function formatPrice(value: number | null | undefined): string {
  return finite(value) ? value.toFixed(2) : '—';
}

export function formatAmountYi(value: number | null | undefined): string {
  return finite(value) ? `${(value / 1e8).toFixed(2)} 亿` : '—';
}

export function formatRankDelta(value: number | null | undefined): string {
  if (!finite(value)) return '—';
  if (value === 0) return '持平';
  return value > 0 ? `↑${value} 名` : `↓${Math.abs(value)} 名`;
}

export function toneClass(value: number | null | undefined): string {
  if (!finite(value) || value === 0) return 'text-muted-foreground';
  return value > 0 ? 'text-market-up' : 'text-market-down';
}

export function breadthCountsLabel(count: number | null | undefined, valid: number | null | undefined, kind: 'up' | 'ma'): string {
  if (!finite(valid) || valid <= 0 || !finite(count)) return '有效样本不足，暂无该项统计';
  if (kind === 'up') return `有效 ${valid} 只，上涨 ${count} 只`;
  return `有效 ${valid} 只，站上均线 ${count} 只`;
}

export type BreadthKind = 'up' | 'ma5' | 'ma20';

export function breadthMissingReason(row: IndustrySnapshot, kind: BreadthKind): string | null {
  const ratio = kind === 'up' ? row.upRatio : kind === 'ma5' ? row.aboveMa5Ratio : row.aboveMa20Ratio;
  if (ratio != null) return null;
  if (row.quality.breadthStatus === 'unavailable_historical_members') {
    return '缺少当日成分记录，历史广度不可用';
  }
  const coverage = kind === 'up'
    ? row.quality.dailyBreadthCoverage
    : kind === 'ma5'
      ? row.quality.ma5Coverage
      : row.quality.ma20Coverage;
  if (coverageBelowThreshold(coverage)) return '成分覆盖不足，该项比例暂不可用';
  return '数据暂不可用';
}

export function rankChangeMissingReason(value: number | null | undefined): string | null {
  if (value != null) return null;
  return '对应历史交易日尚无该行业快照，排名变化暂不可用';
}

export const BREADTH_COVERAGE_THRESHOLD = 0.95;

export function coverageBelowThreshold(value: number | null | undefined): boolean {
  return typeof value === 'number' && value < BREADTH_COVERAGE_THRESHOLD;
}

export function coverageInsufficient(row: IndustrySnapshot): boolean {
  return coverageBelowThreshold(row.quality.dailyBreadthCoverage)
    || coverageBelowThreshold(row.quality.ma5Coverage)
    || coverageBelowThreshold(row.quality.ma20Coverage);
}

export function historicalMembersUnavailable(rows: IndustrySnapshot[]): boolean {
  return rows.some((row) => row.quality.breadthStatus === 'unavailable_historical_members');
}

export type IndustrySummary = {
  strongest: IndustrySnapshot | null;
  accelerating: IndustrySnapshot | null;
  decelerating: IndustrySnapshot | null;
  advancingCount: number;
  validCount: number;
  advancingLabel: string;
};

export function computeSummary(rows: IndustrySnapshot[]): IndustrySummary {
  const valid = rows.filter((row) => finite(row.ret1D));
  const strongest = [...rows].sort((a, b) => a.strengthRank - b.strengthRank)[0] ?? null;
  const accelerating = [...rows]
    .filter((row) => row.momentumAcceleration5D > 0)
    .sort((a, b) => b.momentumAcceleration5D - a.momentumAcceleration5D)[0] ?? null;
  const decelerating = [...rows]
    .filter((row) => row.momentumAcceleration5D < 0)
    .sort((a, b) => a.momentumAcceleration5D - b.momentumAcceleration5D)[0] ?? null;
  const advancingCount = valid.filter((row) => row.ret1D > 0).length;
  return {
    strongest,
    accelerating,
    decelerating,
    advancingCount,
    validCount: valid.length,
    advancingLabel: valid.length === 0 ? '暂无有效行业' : `${formatPercent(advancingCount / valid.length)}（${advancingCount} / ${valid.length}）`,
  };
}

export function stateCounts(rows: IndustrySnapshot[]): Record<'ALL' | IndustryState, number> {
  const counts = { ALL: rows.length, EMERGING: 0, STRONG: 0, NEUTRAL: 0, COOLING: 0, WEAK: 0 };
  for (const row of rows) counts[row.state] += 1;
  return counts;
}

export function filterRankingRows(
  rows: IndustrySnapshot[],
  query: string,
  state: 'ALL' | IndustryState,
): IndustrySnapshot[] {
  const needle = query.trim().toLowerCase();
  return rows.filter((row) => {
    if (state !== 'ALL' && row.state !== state) return false;
    if (!needle) return true;
    return row.industryName.toLowerCase().includes(needle) || row.industryCode.toLowerCase().includes(needle);
  });
}

export function matchesSearch(row: IndustrySnapshot, query: string): boolean {
  return filterRankingRows([row], query, 'ALL').length === 1;
}

export const CORE_COLUMN_KEYS = [
  'strengthRank',
  'industryName',
  'state',
  'strengthScore',
  'rankChange1D',
  'rs5D',
  'momentumAcceleration5D',
  'upRatio',
  'aboveMa20Ratio',
] as const;

export type RankingColumnKey =
  | typeof CORE_COLUMN_KEYS[number]
  | 'rankChange3D'
  | 'rankChange5D'
  | 'rs10D'
  | 'rs20D'
  | 'ret5D'
  | 'ret10D'
  | 'ret20D'
  | 'aboveMa5Ratio'
  | 'turnoverRatio5D';

export type RankingColumn = {
  key: RankingColumnKey;
  label: string;
  short: string;
  unit: string;
  hint: string;
  core: boolean;
  numeric: boolean;
};

export const rankingColumns: RankingColumn[] = [
  {
    key: 'strengthRank',
    label: '强度排名',
    short: '排名',
    unit: '',
    hint: '当日完整截面按综合强度降序的原始排名，1 为最强。筛选或列排序不会重新编号。',
    core: true,
    numeric: true,
  },
  {
    key: 'industryName',
    label: '行业',
    short: '行业',
    unit: '',
    hint: '扶摇 / 同花顺行业指数名称与代码。',
    core: true,
    numeric: false,
  },
  {
    key: 'state',
    label: '状态',
    short: '状态',
    unit: '',
    hint: '按固定规则判定的市场环境标签，不是买入或卖出信号。',
    core: true,
    numeric: false,
  },
  {
    key: 'strengthScore',
    label: '综合强度',
    short: '综合强度',
    unit: '',
    hint: '由 5/10/20 日超额分位加权得到，范围约 0–100，不是买入概率。',
    core: true,
    numeric: true,
  },
  {
    key: 'rankChange1D',
    label: '1 日排名变化',
    short: '1 日变化',
    unit: '名',
    hint: '上一交易日排名 − 当日排名。正数为上升，负数为下降；缺失表示尚无对应历史快照，不能记为持平。',
    core: true,
    numeric: true,
  },
  {
    key: 'rankChange3D',
    label: '3 日排名变化',
    short: '3 日变化',
    unit: '名',
    hint: '3 个交易日前排名 − 当日排名。正数为上升。',
    core: false,
    numeric: true,
  },
  {
    key: 'rankChange5D',
    label: '5 日排名变化',
    short: '5 日变化',
    unit: '名',
    hint: '5 个交易日前排名 − 当日排名。正数为上升。',
    core: false,
    numeric: true,
  },
  {
    key: 'rs5D',
    label: '5 日超额收益',
    short: '5 日超额',
    unit: '百分点',
    hint: '近 5 个交易日行业指数收益减去同期沪深300收益，单位为百分点。',
    core: true,
    numeric: true,
  },
  {
    key: 'rs10D',
    label: '10 日超额收益',
    short: '10 日超额',
    unit: '百分点',
    hint: '近 10 个交易日行业指数收益减去同期沪深300收益，单位为百分点。',
    core: false,
    numeric: true,
  },
  {
    key: 'rs20D',
    label: '20 日超额收益',
    short: '20 日超额',
    unit: '百分点',
    hint: '近 20 个交易日行业指数收益减去同期沪深300收益，单位为百分点。',
    core: false,
    numeric: true,
  },
  {
    key: 'ret5D',
    label: '5 日收益',
    short: '5 日收益',
    unit: '%',
    hint: '行业指数近 5 个交易日涨跌幅。',
    core: false,
    numeric: true,
  },
  {
    key: 'ret10D',
    label: '10 日收益',
    short: '10 日收益',
    unit: '%',
    hint: '行业指数近 10 个交易日涨跌幅。',
    core: false,
    numeric: true,
  },
  {
    key: 'ret20D',
    label: '20 日收益',
    short: '20 日收益',
    unit: '%',
    hint: '行业指数近 20 个交易日涨跌幅。',
    core: false,
    numeric: true,
  },
  {
    key: 'momentumAcceleration5D',
    label: '5 日动量变化',
    short: '5 日动量',
    unit: '百分点',
    hint: '近 5 日收益减去再往前 5 日收益。正值为加速，负值为降速，不是资金流出。',
    core: true,
    numeric: true,
  },
  {
    key: 'upRatio',
    label: '成分股上涨占比',
    short: '上涨占比',
    unit: '%',
    hint: '当日有效成分中收盘上涨的比例。等权涨跌是内部广度代理，不代表行业指数贡献。',
    core: true,
    numeric: true,
  },
  {
    key: 'aboveMa5Ratio',
    label: '站上 MA5 的成分股占比',
    short: 'MA5 上方',
    unit: '%',
    hint: '最近 5 日行情完整的成分中，收盘价高于 5 日均价的比例。',
    core: false,
    numeric: true,
  },
  {
    key: 'aboveMa20Ratio',
    label: '站上 MA20 的成分股占比',
    short: 'MA20 上方',
    unit: '%',
    hint: '最近 20 日行情完整的成分中，收盘价高于 20 日均价的比例。',
    core: true,
    numeric: true,
  },
  {
    key: 'turnoverRatio5D',
    label: '成交额脉冲',
    short: '成交脉冲',
    unit: '×',
    hint: '近 5 日成交额均值相对近 20 日均值的倍数，不是市值或资金净流入。',
    core: false,
    numeric: true,
  },
];

export const POINT_KEYS = new Set<RankingColumnKey>(['rs5D', 'rs10D', 'rs20D', 'momentumAcceleration5D']);
export const PERCENT_KEYS = new Set<RankingColumnKey>(['upRatio', 'aboveMa5Ratio', 'aboveMa20Ratio', 'ret5D', 'ret10D', 'ret20D']);
export const RANK_DELTA_KEYS = new Set<RankingColumnKey>(['rankChange1D', 'rankChange3D', 'rankChange5D']);

export function formatRankingCell(row: IndustrySnapshot, key: RankingColumnKey, compact = true): string {
  if (key === 'strengthRank') return String(row.strengthRank);
  if (key === 'industryName') return row.industryName;
  if (key === 'state') return stateLabels[row.state];
  if (key === 'strengthScore') return formatScore(row.strengthScore);
  if (RANK_DELTA_KEYS.has(key)) return formatRankDelta(row[key] as number | null);
  if (POINT_KEYS.has(key)) return formatPoints(row[key] as number, { unit: !compact });
  if (PERCENT_KEYS.has(key)) return formatPercent(row[key] as number, { unit: !compact, digits: 1 });
  if (key === 'turnoverRatio5D') return formatPulse(row.turnoverRatio5D, { unit: !compact });
  return '—';
}

export function bubbleSize(turnover: number): number {
  return Math.max(9, Math.min(40, 18 * Math.sqrt(Math.max(0, turnover))));
}

export function heatmapNormalizedRank(rank: number, rankedCount: number): number {
  if (rankedCount <= 1) return 50;
  return 100 * (rankedCount - rank) / (rankedCount - 1);
}

export function selectedDateLeaders(rows: IndustrySnapshot[], limit = 20): IndustrySnapshot[] {
  return [...rows].sort((a, b) => a.strengthRank - b.strengthRank).slice(0, limit);
}

export const heatmapMissingColor = { light: '#d4d4d8', dark: '#3f3f46' };

/** @deprecated use formatPercent / formatPoints */
export const pct = formatPercent;
export const num = formatScore;
export function delta(value: number | null): string {
  return formatRankDelta(value);
}
export const tone = toneClass;
export function breadthLabel(ratio: number | null, count: number | null, valid: number | null): string {
  return ratio == null || !valid ? '—' : `${formatPercent(ratio)}（${count}/${valid}）`;
}
