import camelcaseKeys from 'camelcase-keys';
import {
  RANKING_FEATURE_KEYS,
  type RankingFeatureKey,
  type TrendRankingFeatures,
  type TrendRankingSnapshot,
  type TrendSnapshot,
  type TrendState,
} from '@/types/trendFollowing';

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function nestedRecord(value: Record<string, unknown>, key: string): Record<string, unknown> {
  const nested = value[key];
  return isRecord(nested) ? nested : {};
}

function firstNumber(record: Record<string, unknown>, ...keys: string[]): number | null {
  for (const key of keys) {
    const value = finiteNumber(record[key]);
    if (value != null) return value;
  }
  return null;
}

function recordValues(value: object): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) result[key] = item;
  return result;
}

type QualityFeatureKey = Extract<RankingFeatureKey,
  | 'r2Quality' | 'momentumQuality' | 'return10DQuality' | 'return20DQuality' | 'drawdownQuality'
  | 'rs5DQuality' | 'rs10DQuality' | 'rs20DQuality'
  | 'breakoutQuality' | 'extensionQuality' | 'volumeQuality' | 'compressionQuality'
  | 'concentrationQuality' | 'volatilityQuality'
  | 'alphaTrendContribution' | 'alphaRsContribution' | 'alphaSetupContribution' | 'alphaPathContribution'
>;

function assignQuality(target: TrendRankingFeatures, key: QualityFeatureKey, value: number | null) {
  if (value != null) target[key] = value;
}

export function rankingFeaturesFromBreakdown(breakdown: unknown): TrendRankingFeatures {
  if (!isRecord(breakdown)) return {};
  const trend = nestedRecord(breakdown, 'trend');
  const rs = nestedRecord(breakdown, 'rs');
  const qualities = isRecord(rs.qualities) ? rs.qualities : {};
  const setup = nestedRecord(breakdown, 'setup');
  const path = nestedRecord(breakdown, 'path');
  const alpha = nestedRecord(breakdown, 'alpha');
  const contributions = isRecord(alpha.contributions) ? alpha.contributions : {};
  const result: TrendRankingFeatures = {};
  assignQuality(result, 'r2Quality', firstNumber(trend, 'weightedR2', 'weighted_r2'));
  assignQuality(result, 'momentumQuality', firstNumber(trend, 'momentum'));
  assignQuality(result, 'return10DQuality', firstNumber(trend, 'return10D', 'return_10d'));
  assignQuality(result, 'return20DQuality', firstNumber(trend, 'return20D', 'return_20d'));
  assignQuality(result, 'drawdownQuality', firstNumber(trend, 'drawdownQuality', 'drawdown_quality'));
  assignQuality(result, 'rs5DQuality', firstNumber(qualities, 'rs5D', 'rs_5d'));
  assignQuality(result, 'rs10DQuality', firstNumber(qualities, 'rs10D', 'rs_10d'));
  assignQuality(result, 'rs20DQuality', firstNumber(qualities, 'rs20D', 'rs_20d'));
  assignQuality(result, 'breakoutQuality', firstNumber(setup, 'breakoutQuality', 'breakout_quality'));
  assignQuality(result, 'extensionQuality', firstNumber(setup, 'extensionQuality', 'extension_quality'));
  assignQuality(result, 'volumeQuality', firstNumber(setup, 'volumeQuality', 'volume_quality'));
  assignQuality(result, 'compressionQuality', firstNumber(setup, 'compressionQuality', 'compression_quality'));
  assignQuality(result, 'concentrationQuality', firstNumber(path, 'concentrationQuality', 'concentration_quality'));
  assignQuality(result, 'volatilityQuality', firstNumber(path, 'volatilityQuality', 'volatility_quality'));
  assignQuality(result, 'alphaTrendContribution', firstNumber(contributions, 'trend'));
  assignQuality(result, 'alphaRsContribution', firstNumber(contributions, 'rs'));
  assignQuality(result, 'alphaSetupContribution', firstNumber(contributions, 'setup'));
  assignQuality(result, 'alphaPathContribution', firstNumber(contributions, 'path'));
  return result;
}

export function mergeRankingFeatures(
  features: Record<string, unknown>,
  extras: TrendRankingFeatures = {},
): TrendRankingFeatures {
  const result: TrendRankingFeatures = {};
  for (const key of RANKING_FEATURE_KEYS) {
    const extra = extras[key];
    if (typeof extra === 'number' && Number.isFinite(extra)) {
      result[key] = extra;
      continue;
    }
    if (typeof extra === 'boolean') {
      result[key] = extra;
      continue;
    }
    if (!(key in features)) continue;
    const raw = features[key];
    if (typeof raw === 'number' && Number.isFinite(raw)) result[key] = raw;
    else if (typeof raw === 'boolean') result[key] = raw;
    else result[key] = null;
  }
  return result;
}

export function asRankingSnapshot(snapshot: Pick<TrendSnapshot,
  'code' | 'name' | 'rank' | 'state' | 'trendDurationDays' | 'trendLifecycle' |
  'fragilityScore' | 'alphaScore' | 'trendScore' | 'rsScore' | 'breakoutScore' |
  'setup' | 'atr' | 'referencePrice'> & {
  features: Record<string, unknown>;
  scoreBreakdown?: unknown;
}): TrendRankingSnapshot {
  return {
    code: snapshot.code,
    name: snapshot.name,
    rank: snapshot.rank,
    state: snapshot.state,
    trendDurationDays: snapshot.trendDurationDays,
    trendLifecycle: snapshot.trendLifecycle,
    fragilityScore: snapshot.fragilityScore,
    alphaScore: snapshot.alphaScore,
    trendScore: snapshot.trendScore,
    rsScore: snapshot.rsScore,
    breakoutScore: snapshot.breakoutScore,
    setup: snapshot.setup,
    atr: snapshot.atr,
    referencePrice: snapshot.referencePrice,
    features: mergeRankingFeatures(
      snapshot.features,
      rankingFeaturesFromBreakdown(snapshot.scoreBreakdown),
    ),
    rankChange1D: null,
    rankChange3D: null,
    rankChange5D: null,
  };
}

export function rankingFeatureValue(
  item: TrendRankingSnapshot,
  key: RankingFeatureKey,
): number | boolean | null {
  const value = item.features[key];
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'boolean') return value;
  return null;
}

const TREND_STATES = ['IDLE', 'WATCHING', 'CANDIDATE', 'TRENDING', 'WEAKENING', 'BROKEN'] as const;
const LIFECYCLES = ['IGNITION', 'EMERGING', 'EXPANSION', 'MATURE', 'EXHAUSTION', 'BROKEN'] as const;

function textValue(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value);
}

function optionalText(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function intValue(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function isTrendState(value: unknown): value is TrendState {
  return typeof value === 'string' && TREND_STATES.some(state => state === value);
}

function isLifecycle(value: unknown): value is typeof LIFECYCLES[number] {
  return typeof value === 'string' && LIFECYCLES.some(item => item === value);
}

export function rankingSnapshotFromDto(row: Record<string, unknown>): TrendRankingSnapshot {
  const mapped = recordValues(camelcaseKeys(row));
  const featureSource = isRecord(row.features) ? recordValues(camelcaseKeys(row.features)) : {};
  return {
    code: textValue(mapped.code),
    name: textValue(mapped.name),
    rank: intValue(mapped.rank),
    state: isTrendState(mapped.state) ? mapped.state : null,
    trendDurationDays: finiteNumber(mapped.trendDurationDays),
    trendLifecycle: isLifecycle(mapped.trendLifecycle) ? mapped.trendLifecycle : null,
    fragilityScore: finiteNumber(mapped.fragilityScore),
    alphaScore: finiteNumber(mapped.alphaScore) ?? 0,
    trendScore: finiteNumber(mapped.trendScore),
    rsScore: finiteNumber(mapped.rsScore),
    breakoutScore: finiteNumber(mapped.breakoutScore),
    setup: optionalText(mapped.setup),
    atr: finiteNumber(mapped.atr),
    referencePrice: finiteNumber(mapped.referencePrice),
    features: mergeRankingFeatures(featureSource, rankingFeaturesFromBreakdown(row.score_breakdown ?? row.scoreBreakdown)),
    rankChange1D: finiteNumber(mapped.rankChange1D),
    rankChange3D: finiteNumber(mapped.rankChange3D),
    rankChange5D: finiteNumber(mapped.rankChange5D),
  };
}
