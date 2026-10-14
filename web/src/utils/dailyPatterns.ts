import type { DailyBar } from '@/api/marketData';

export type DailyPatternType = 'bullish_engulfing' | 'bearish_engulfing' | 'hammer' |
  'shooting_star' | 'morning_star' | 'evening_star' | 'piercing_line' | 'dark_cloud_cover' |
  'inverted_hammer' | 'hanging_man' | 'bullish_harami' | 'bearish_harami' |
  'three_white_soldiers' | 'three_black_crows' | 'doji';
export type DailyPatternDirection = 'bullish' | 'bearish' | 'neutral';
export interface DailyPatternEvent {
  date: string;
  timestamp: number;
  type: DailyPatternType;
  name: string;
  direction: DailyPatternDirection;
  quality: number;
  confirmed: boolean;
  reasons: string[];
}
export interface DailyPatternOptions {
  /** Snapshot of the market-local date when bars were fetched; no implicit clock in detection. */
  marketDate?: string;
  minQuality?: number;
}
export const DAILY_PATTERN_MIN_QUALITY = 70;
export const DAILY_PATTERN_DEFINITIONS = {
  bullish_engulfing: { name: '看涨吞没', priority: 2 },
  bearish_engulfing: { name: '看跌吞没', priority: 2 },
  hammer: { name: '锤子线', priority: 1 },
  shooting_star: { name: '射击之星', priority: 1 },
  morning_star: { name: '晨星', priority: 3 },
  evening_star: { name: '黄昏星', priority: 3 },
  piercing_line: { name: '刺透线', priority: 2 },
  dark_cloud_cover: { name: '乌云盖顶', priority: 2 },
  inverted_hammer: { name: '倒锤子线', priority: 1 },
  hanging_man: { name: '上吊线', priority: 1 },
  bullish_harami: { name: '看涨孕线', priority: 2 },
  bearish_harami: { name: '看跌孕线', priority: 2 },
  three_white_soldiers: { name: '红三兵', priority: 3 },
  three_black_crows: { name: '三只乌鸦', priority: 3 },
  doji: { name: '十字星', priority: 1 },
} as const;
const definitions = DAILY_PATTERN_DEFINITIONS;
/** Quality wins; specificity only breaks equal-score ties for display. */
export function compareDailyPatternCandidates(
  a: Pick<DailyPatternEvent, 'quality' | 'type'>, b: Pick<DailyPatternEvent, 'quality' | 'type'>,
): number {
  return b.quality - a.quality || definitions[b.type].priority - definitions[a.type].priority || a.type.localeCompare(b.type);
}
const clamp = (value: number) => Math.max(0, Math.min(1, value));
function geometry(bar: DailyBar) {
  const body = Math.abs(bar.close - bar.open);
  const range = bar.high - bar.low;
  const upperShadow = bar.high - Math.max(bar.open, bar.close);
  const lowerShadow = Math.min(bar.open, bar.close) - bar.low;
  return { body, range, upperShadow, lowerShadow, bodyRatio: body / range };
}
export function isValidDailyBar(bar: DailyBar) {
  return [bar.open, bar.high, bar.low, bar.close].every(value => Number.isFinite(value) && value > 0) &&
    bar.high > bar.low && bar.high >= Math.max(bar.open, bar.close) && bar.low <= Math.min(bar.open, bar.close);
}
const valid = isValidDailyBar;
/** Conservative fallback: today's bar stays Preview even after the nominal close.
 * No exchange calendar/closed flag is available in daily-bars. Unknown market => unconfirmed.
 */
export function dailyPatternMarketDate(market: string, now: Date): string | undefined {
  const timeZone = ({ CN: 'Asia/Shanghai', HK: 'Asia/Hong_Kong', US: 'America/New_York' } as Record<string, string>)[market];
  if (!timeZone || !Number.isFinite(now.getTime())) return undefined;
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' })
    .formatToParts(now);
  const get = (type: string) => parts.find(part => part.type === type)!.value;
  return `${get('year')}-${get('month')}-${get('day')}`;
}

/** Sorted, unique trading dates as supplied by daily-bars. Invalid bars break the lookback;
 * they are never removed to fabricate adjacent sessions. Uses only bars up to the event date.
 */
export function detectDailyPatterns(bars: readonly DailyBar[], options: DailyPatternOptions = {}): DailyPatternEvent[] {
  const events: DailyPatternEvent[] = [];
  for (let end = 6; end < bars.length; end++) {
    const current = bars[end]!;
    const confirmed = !!options.marketDate && current.tradeDate < options.marketDate;
    const candidates: DailyPatternEvent[] = [];
    const add = (type: DailyPatternType, bullish: boolean, length: number, strength: number, reason: string) => {
      const start = end - length + 1;
      if (start < 6) return;
      const window = bars.slice(start - 6, end + 1);
      if (!window.every((bar, i) => valid(bar) && (i === 0 || bar.tradeDate > window[i - 1]!.tradeDate))) return;
      const prior = bars.slice(start - 6, start);
      const priorReturn = prior[5]!.close / prior[0]!.close - 1;
      const sign = bullish ? -1 : 1;
      const move = sign * priorReturn;
      const steps = prior.slice(1).filter((bar, i) => sign * (bar.close - prior[i]!.close) > 0).length;
      // Five preceding close-to-close changes, excluding ALL candles of the pattern.
      if (!(move >= 0.02 || (steps >= 4 && move >= 0.01))) return;
      const g = geometry(current);
      const closeLocation = bullish ? (current.close - current.low) / g.range : (current.high - current.close) / g.range;
      // Trend excludes the whole pattern; volume excludes only the completion candle.
      // Earlier candles of a multi-day pattern are completed historical volume samples.
      const volumeReference = bars.slice(Math.max(0, end - 20), end);
      const volumes = volumeReference.map(bar => bar.volume).filter(value => Number.isFinite(value) && value > 0);
      const averageVolume = volumes.reduce((sum, value) => sum + value, 0) / volumes.length;
      const volumeBonus = confirmed && volumes.length >= 10 && Number.isFinite(current.volume)
        ? 5 * clamp((current.volume / averageVolume - 1) / 0.5) : 0;
      const trendScore = 15 * clamp(move / 0.05) + 10 * steps / 5;
      const quality = Math.round(40 + 20 * clamp(strength) + trendScore + 10 * closeLocation + volumeBonus);
      if (quality < Math.max(DAILY_PATTERN_MIN_QUALITY, options.minQuality ?? DAILY_PATTERN_MIN_QUALITY)) return;
      const reasons = [reason,
        `形态开始前 5 个交易日累计${bullish ? '下跌' : '上涨'} ${(move * 100).toFixed(1)}%，其中 ${steps}/5 日收盘${bullish ? '下降' : '上升'}`,
        `收盘位于当日区间${bullish ? '下沿向上' : '上沿向下'} ${(closeLocation * 100).toFixed(0)}% 处`];
      if (volumeBonus > 0) reasons.push(`形态完成日成交量为此前最多 20 个交易日中 ${volumes.length} 个有效样本均量的 ${(current.volume / averageVolume).toFixed(2)} 倍（轻量加分）`);
      candidates.push({ date: current.tradeDate, timestamp: Date.parse(`${current.tradeDate}T00:00:00Z`),
        type, name: definitions[type].name, direction: bullish ? 'bullish' : 'bearish', quality,
        confirmed, reasons });
    };
    if (!valid(current)) continue;
    const g = geometry(current);
    const previous = bars[end - 1]!;
    const p = geometry(previous);
    for (const bullish of [true, false]) {
      const sign = bullish ? 1 : -1;
      const directional = sign * (current.close - current.open) > 0;
      const strongBody = directional && g.bodyRatio >= 0.55 && g.body / previous.close >= 0.005;
      const engulfed = bullish
        ? current.open <= previous.close && current.close >= previous.open
        : current.open >= previous.close && current.close <= previous.open;
      if (strongBody && sign * (previous.close - previous.open) < 0 && engulfed &&
        p.bodyRatio >= 0.2 && p.body / previous.close >= 0.002 && g.body >= p.body * 1.1) {
        add(bullish ? 'bullish_engulfing' : 'bearish_engulfing', bullish, 2,
          (g.body / p.body - 1) / 1.5,
          `${bullish ? '阳' : '阴'}线实体完整吞没前一日${bullish ? '阴' : '阳'}线实体，实体为前一日的 ${(g.body / p.body).toFixed(2)} 倍`);
      }
      const longShadow = bullish ? g.lowerShadow : g.upperShadow;
      const shortShadow = bullish ? g.upperShadow : g.lowerShadow;
      if (g.bodyRatio >= 0.15 && g.bodyRatio <= 0.35 && g.body / current.close >= 0.002 &&
        longShadow >= g.body * 2 && shortShadow <= g.body * 0.5) {
        add(bullish ? 'hammer' : 'shooting_star', bullish, 1,
          (longShadow / g.body - 2) / 2,
          `${bullish ? '下' : '上'}影线为实体的 ${(longShadow / g.body).toFixed(2)} 倍，${bullish ? '上' : '下'}影线不超过实体一半，实体占振幅 ${(g.bodyRatio * 100).toFixed(0)}%`);
      }
      // Same geometry, different preceding trend: inverted hammer and hanging man.
      if (g.bodyRatio >= 0.15 && g.bodyRatio <= 0.35 && g.body / current.close >= 0.002 &&
        shortShadow >= g.body * 2 && longShadow <= g.body * 0.5) {
        add(bullish ? 'inverted_hammer' : 'hanging_man', bullish, 1,
          (shortShadow / g.body - 2) / 2,
          `${bullish ? '上' : '下'}影线为实体的 ${(shortShadow / g.body).toFixed(2)} 倍；结合此前${bullish ? '下跌' : '上涨'}趋势观察反转`);
      }
      const penetrationPrevious = sign * (current.close - previous.close) / p.body;
      const opensBeyondClose = sign * (current.open - previous.close) <= 0;
      if (strongBody && sign * (previous.close - previous.open) < 0 && p.bodyRatio >= 0.55 &&
        p.body / previous.close >= 0.005 && opensBeyondClose && penetrationPrevious >= 0.5 && penetrationPrevious < 1) {
        add(bullish ? 'piercing_line' : 'dark_cloud_cover', bullish, 2, penetrationPrevious,
          `反向大实体收盘穿透前一根实体 ${(penetrationPrevious * 100).toFixed(0)}%，未完整吞没；不要求跳空`);
      }
      const insideBody = Math.min(current.open, current.close) >= Math.min(previous.open, previous.close) &&
        Math.max(current.open, current.close) <= Math.max(previous.open, previous.close);
      if (directional && insideBody && p.bodyRatio >= 0.55 && p.body / previous.close >= 0.005 &&
        sign * (previous.close - previous.open) < 0 && g.body / current.close >= 0.002 &&
        g.bodyRatio >= 0.2 && g.body <= p.body * 0.5) {
        add(bullish ? 'bullish_harami' : 'bearish_harami', bullish, 2, 1 - g.body / p.body,
          `反向小实体包含于前一根大实体内，实体为前一日的 ${(g.body / p.body * 100).toFixed(0)}%`);
      }
      const first = bars[end - 2]!;
      const f = geometry(first);
      const trio = [first, previous, current];
      if (trio.every(bar => {
        const shape = geometry(bar);
        const tip = bullish ? shape.upperShadow : shape.lowerShadow;
        return sign * (bar.close - bar.open) > 0 && shape.bodyRatio >= 0.55 &&
          shape.body / bar.close >= 0.005 && tip <= shape.body * 0.35;
      }) && sign * (previous.close - first.close) > 0 && sign * (current.close - previous.close) > 0 &&
        trio.slice(1).every((bar, i) => bar.open >= Math.min(trio[i]!.open, trio[i]!.close) &&
          bar.open <= Math.max(trio[i]!.open, trio[i]!.close))) {
        add(bullish ? 'three_white_soldiers' : 'three_black_crows', bullish, 3,
          Math.min(...trio.map(bar => geometry(bar).bodyRatio)),
          `连续三根${bullish ? '阳' : '阴'}线，收盘逐根${bullish ? '抬高' : '降低'}，开盘位于前根实体内且方向端影线短`);
      }
      const penetration = sign * (current.close - first.close) / f.body;
      const middleAtExtreme = bullish
        ? Math.max(previous.open, previous.close) <= first.close + 0.25 * f.body
        : Math.min(previous.open, previous.close) >= first.close - 0.25 * f.body;
      if (strongBody && sign * (first.close - first.open) < 0 && f.bodyRatio >= 0.55 &&
        f.body / first.close >= 0.005 && p.body <= f.body * 0.3 && p.bodyRatio <= 0.35 &&
        middleAtExtreme && g.body >= f.body * 0.6 && penetration >= 0.6) {
        add(bullish ? 'morning_star' : 'evening_star', bullish, 3,
          (penetration - 0.5) / 0.5,
          `首根明显${bullish ? '阴' : '阳'}线、次根小实体、第三根明显${bullish ? '阳' : '阴'}线；收盘穿透首根实体 ${(penetration * 100).toFixed(0)}%（不要求跳空）`);
      }
    }
    // Neutral observation, with no bullish/bearish assignment or volume score.
    const context = bars.slice(end - 6, end + 1);
    if (context.every((bar, i) => valid(bar) && (i === 0 || bar.tradeDate > context[i - 1]!.tradeDate)) &&
      g.bodyRatio <= 0.08 && g.range / current.close >= 0.015 &&
      g.upperShadow >= g.range * 0.3 && g.lowerShadow >= g.range * 0.3) {
      const quality = Math.round(70 + 15 * (1 - g.bodyRatio / 0.08) +
        15 * Math.min(g.upperShadow, g.lowerShadow) / Math.max(g.upperShadow, g.lowerShadow));
      if (quality >= (options.minQuality ?? DAILY_PATTERN_MIN_QUALITY)) candidates.push({
        date: current.tradeDate, timestamp: Date.parse(`${current.tradeDate}T00:00:00Z`),
        type: 'doji', name: definitions.doji.name, direction: 'neutral', quality, confirmed,
        reasons: [`实体占振幅 ${(g.bodyRatio * 100).toFixed(1)}%，上下影线各占振幅至少30%`,
          '表示多空犹豫，仅作中性观察；不直接判定上涨、下跌或反转'],
      });
    }
    candidates.sort(compareDailyPatternCandidates);
    if (candidates[0]) events.push(candidates[0]);
  }
  return events;
}
