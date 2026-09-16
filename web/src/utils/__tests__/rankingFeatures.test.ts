import { describe, expect, it } from 'vitest';
import {
  asRankingSnapshot,
  mergeRankingFeatures,
  rankingFeatureValue,
  rankingFeaturesFromBreakdown,
  rankingSnapshotFromDto,
} from '../rankingFeatures';

const breakdown = {
  trend: { weighted_r2: 90, momentum: 70, return_10d: 68, return_20d: 64, drawdown_quality: 81 },
  rs: { qualities: { rs_5d: 55, rs_10d: 61, rs_20d: 58 } },
  setup: { breakout_quality: 77, extension_quality: 66, volume_quality: 80, compression_quality: 40 },
  path: { concentration_quality: 88, volatility_quality: 72 },
  alpha: { version: 2, contributions: { trend: 32, rs: 17.5, setup: 12, path: 18 } },
};

describe('rankingFeaturesFromBreakdown', () => {
  it('projects V2 quality scalars and omits missing paths', () => {
    expect(rankingFeaturesFromBreakdown(breakdown)).toEqual({
      r2Quality: 90, momentumQuality: 70, return10DQuality: 68, return20DQuality: 64, drawdownQuality: 81,
      rs5DQuality: 55, rs10DQuality: 61, rs20DQuality: 58,
      breakoutQuality: 77, extensionQuality: 66, volumeQuality: 80, compressionQuality: 40,
      concentrationQuality: 88, volatilityQuality: 72,
      alphaTrendContribution: 32, alphaRsContribution: 17.5, alphaSetupContribution: 12, alphaPathContribution: 18,
    });
    expect(rankingFeaturesFromBreakdown({ alpha: { version: 1 } })).toEqual({});
    expect(rankingFeaturesFromBreakdown(undefined)).toEqual({});
  });

  it('accepts camelCase preview breakdowns', () => {
    expect(rankingFeaturesFromBreakdown({
      trend: { weightedR2: 91 },
      rs: { qualities: { rs10D: 62 } },
      setup: { volumeQuality: 81 },
      path: { concentrationQuality: 89 },
      alpha: { contributions: { trend: 33 } },
    })).toEqual({
      r2Quality: 91, rs10DQuality: 62, volumeQuality: 81, concentrationQuality: 89, alphaTrendContribution: 33,
    });
  });
});

describe('mergeRankingFeatures', () => {
  it('keeps explicit nulls, omits absent keys, and prefers projected qualities', () => {
    expect(mergeRankingFeatures({})).toEqual({});
    expect(mergeRankingFeatures({ r2Quality: null, trendCandidate: false })).toEqual({
      r2Quality: null, trendCandidate: false,
    });
    expect(mergeRankingFeatures({ r2Quality: 12, volumeRatio: 1.4 }, { r2Quality: 90 })).toEqual({
      r2Quality: 90, volumeRatio: 1.4,
    });
  });
});

describe('rankingSnapshotFromDto', () => {
  it('maps nullable ranking features without fabricating V2 scores', () => {
    const row = rankingSnapshotFromDto({
      code: 'AAPL.US', name: 'Apple', rank: 3, state: 'TRENDING', alpha_score: 82,
      features: { r2_quality: null, trend_candidate: true, prior_compression: false },
    });
    expect(row.features).toEqual({ r2Quality: null, trendCandidate: true, priorCompression: false });
    expect(rankingFeatureValue(row, 'r2Quality')).toBeNull();
    expect(rankingFeatureValue(row, 'drawdownQuality')).toBeNull();
    expect(rankingFeatureValue(row, 'trendCandidate')).toBe(true);
    expect(row).not.toHaveProperty('scoreBreakdown');
  });

  it('keeps null ranking scalars and unknown state instead of fabricating defaults', () => {
    const row = rankingSnapshotFromDto({
      code: 'NULL.US', rank: 8, alpha_score: 70,
      state: null, trend_score: null, rs_score: null, breakout_score: null,
      atr: null, reference_price: null, setup: null,
    });
    expect(row).toMatchObject({
      code: 'NULL.US', rank: 8, alphaScore: 70,
      state: null, trendScore: null, rsScore: null, breakoutScore: null,
      atr: null, referencePrice: null, setup: null,
    });
    expect(row.state).not.toBe('IDLE');
    expect(row.trendScore).not.toBe(0);
    expect(row.rsScore).not.toBe(0);
    expect(row.breakoutScore).not.toBe(0);
    expect(row.atr).not.toBe(0);
    expect(row.referencePrice).not.toBe(0);
  });

  it('does not coerce a missing or unknown state to IDLE', () => {
    expect(rankingSnapshotFromDto({ code: 'X', rank: 1, alpha_score: 1 }).state).toBeNull();
    expect(rankingSnapshotFromDto({ code: 'X', rank: 1, alpha_score: 1, state: 'UNKNOWN' }).state).toBeNull();
  });
});

describe('asRankingSnapshot', () => {
  it('flattens preview scoreBreakdown qualities onto ranking features', () => {
    const snapshot = {
      code: '600519.SH', name: '贵州茅台', rank: 1, state: 'CANDIDATE' as const,
      trendDurationDays: 4, trendLifecycle: 'EMERGING' as const, fragilityScore: 12,
      alphaScore: 71, trendScore: 80, rsScore: 70, breakoutScore: 60, setup: 'BREAKOUT_20D',
      atr: 2, referencePrice: 110,
      features: { trendCandidate: true, weightedSlopePercentile: 88, priorCompression: true },
      scoreBreakdown: { trend: { weightedR2: 90 }, alpha: { contributions: { trend: 32 } } },
    };
    const row = asRankingSnapshot(snapshot);
    expect(row.features.r2Quality).toBe(90);
    expect(row.features.alphaTrendContribution).toBe(32);
    expect(row.features.trendCandidate).toBe(true);
    expect(row.features.weightedSlopePercentile).toBe(88);
    expect(rankingFeatureValue(row, 'volumeQuality')).toBeNull();
  });
});
