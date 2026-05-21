/**
 * Stock Search Algorithm
 *
 * Supports multiple matching methods:
 * - Exact match: code, name, pinyin, alias
 * - Prefix match: code prefix, name prefix, pinyin prefix
 * - Contains match: code contains, name contains, pinyin contains
 * - Fuzzy match: ordered subsequence (e.g. typos / skipped chars in pinyin or Chinese name)
 */

import type { StockIndexItem, StockSuggestion } from '../types/stockIndex';
import { isStockCodeLike, normalizeQuery } from './normalizeQuery';
import { MATCH_SCORE, SEARCH_CONFIG } from './stockIndexFields';

/** Fuzzy tier scores stay strictly below {@link MATCH_SCORE.CONTAINS_MIN}. */
const FUZZY_SCORE_MAX = MATCH_SCORE.CONTAINS_MIN - 1;

/** Skip fuzzy for single-character queries (too noisy); cap length for performance. */
const FUZZY_MIN_QUERY_LEN = 2;
const FUZZY_MAX_QUERY_LEN = 48;

type MatchField = 'code' | 'name' | 'pinyin' | 'alias';

/**
 * If every character of `query` appears in `text` in order (subsequence), return a score in
 * `[MATCH_SCORE.FUZZY_MIN, FUZZY_SCORE_MAX]`. Otherwise `0`.
 */
function subsequenceFuzzyScore(query: string, text: string): number {
  if (query.length < FUZZY_MIN_QUERY_LEN || query.length > FUZZY_MAX_QUERY_LEN) return 0;
  if (!text) return 0;
  if (query.length > text.length) return 0;

  const q = query.toLowerCase();
  const t = text.toLowerCase();

  let qi = 0;
  let first = -1;
  let prev = -1;
  let gap = 0;

  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) {
      if (prev === -1) {
        first = i;
      } else {
        gap += i - prev - 1;
      }
      prev = i;
      qi++;
    }
  }

  if (qi < q.length || first === -1 || prev === -1) return 0;

  const span = prev - first + 1;
  const coverage = q.length / span;
  const gapSlots = Math.max(1, span - 1);
  const gapNorm = gap / gapSlots;
  const tightness = coverage * (1 - 0.28 * Math.min(1, gapNorm));
  const raw = 1 + (FUZZY_SCORE_MAX - 1) * Math.max(0, Math.min(1, tightness));
  return Math.round(raw);
}

function fieldPriority(field: MatchField): number {
  if (field === 'name') return 4;
  if (field === 'pinyin') return 3;
  if (field === 'alias') return 2;
  return 1;
}

function computeFuzzyMatch(
  query: string,
  item: StockIndexItem,
): { score: number; field: MatchField } {
  const q = query.toLowerCase();
  const candidates: { field: MatchField; text: string }[] = [
    { field: 'name', text: normalizeQuery(item.nameZh) },
    { field: 'pinyin', text: normalizeQuery(item.pinyinFull || '') },
    { field: 'pinyin', text: normalizeQuery(item.pinyinAbbr || '') },
  ];

  for (const alias of item.aliases || []) {
    candidates.push({ field: 'alias', text: normalizeQuery(alias) });
  }

  if (isStockCodeLike(q)) {
    candidates.push(
      { field: 'code', text: normalizeQuery(item.displayCode) },
      { field: 'code', text: normalizeQuery(item.canonicalCode) },
    );
  }

  let bestScore = 0;
  let bestField: MatchField = 'name';

  for (const { field, text } of candidates) {
    const s = subsequenceFuzzyScore(q, text);
    if (s > bestScore || (s === bestScore && s > 0 && fieldPriority(field) > fieldPriority(bestField))) {
      bestScore = s;
      bestField = field;
    }
  }

  return { score: bestScore, field: bestField };
}

export interface SearchOptions {
  /** Limit on number of results to return */
  limit?: number;
  /** Show only active stocks */
  activeOnly?: boolean;
}

/**
 * Search stock index
 *
 * @param query - Search query
 * @param index - Stock index
 * @param options - Search options
 * @returns List of matched stock suggestions
 */
export function searchStocks(
  query: string,
  index: StockIndexItem[],
  options: SearchOptions = {}
): StockSuggestion[] {
  const normalizedQuery = normalizeQuery(query);
  if (!normalizedQuery) {
    return [];
  }
  const limit = options.limit || SEARCH_CONFIG.DEFAULT_LIMIT;
  const activeOnly = options.activeOnly !== false;

  // Filter index
  const filteredIndex = index.filter(item => {
    if (activeOnly && !item.active) return false;
    return true;
  });

  // Calculate match score for each item
  const suggestions = filteredIndex.map(item => {
    const { score, fuzzyField } = calculateMatchScore(normalizedQuery, item);
    return { item, score, fuzzyField };
  });

  // Filter out items with score of 0
  const matched = suggestions.filter(s => s.score > 0);

  // Sort: by score descending, then by popularity descending for same score
  matched.sort((a, b) => {
    if (a.score !== b.score) return b.score - a.score;
    return (b.item.popularity || 0) - (a.item.popularity || 0);
  });

  // Return top N items
  return matched.slice(0, limit).map(s => ({
    canonicalCode: s.item.canonicalCode,
    displayCode: s.item.displayCode,
    nameZh: s.item.nameZh,
    market: s.item.market,
    matchType: determineMatchType(s.score),
    matchField: determineMatchField(normalizedQuery, s.item, s.score, s.fuzzyField),
    score: s.score,
  }));
}

/**
 * Calculate match score
 *
 * Score rules:
 * - 100: Exact match canonical code
 * - 99: Exact match display code
 * - 98: Exact match Chinese name
 * - 97: Exact match alias
 * - 96: Exact match pinyin abbreviation
 * - 80-89: Prefix match
 * - 60-69: Contains match
 * - 1-56: Fuzzy (ordered subsequence on name / pinyin / alias / code when code-like)
 * - 0: No match
 */
function calculateMatchScore(query: string, item: StockIndexItem): { score: number; fuzzyField?: MatchField } {
  let score = 0;
  const q = query.toLowerCase();
  const normalizedCanonicalCode = normalizeQuery(item.canonicalCode);
  const normalizedDisplayCode = normalizeQuery(item.displayCode);
  const normalizedName = normalizeQuery(item.nameZh);
  const normalizedPinyinFull = normalizeQuery(item.pinyinFull || '');
  const normalizedPinyinAbbr = normalizeQuery(item.pinyinAbbr || '');
  const normalizedAliases = item.aliases?.map(alias => normalizeQuery(alias)) || [];

  // 1. Exact match (96-100 points)
  if (q === normalizedCanonicalCode) return { score: 100 };
  if (q === normalizedDisplayCode) return { score: 99 };
  if (q === normalizedName) return { score: 98 };
  if (normalizedAliases.some(a => a === q)) return { score: 97 };
  if (q === normalizedPinyinAbbr) return { score: 96 };

  // 2. Prefix match (77-80 points)
  if (normalizedDisplayCode.startsWith(q)) score = Math.max(score, 80);
  if (normalizedName.startsWith(q)) score = Math.max(score, 79);
  if (normalizedPinyinAbbr.startsWith(q)) score = Math.max(score, 78);
  if (normalizedAliases.some(a => a.startsWith(q))) score = Math.max(score, 77);

  // 3. Contains match (57-60 points)
  if (normalizedDisplayCode.includes(q)) score = Math.max(score, 60);
  if (normalizedName.includes(q)) score = Math.max(score, 59);
  if (normalizedPinyinFull.includes(q)) score = Math.max(score, 58);
  if (normalizedAliases.some(a => a.includes(q))) score = Math.max(score, 57);

  // 4. Fuzzy (subsequence) — only if no stronger tier matched
  if (score < MATCH_SCORE.CONTAINS_MIN) {
    const fuzzy = computeFuzzyMatch(q, item);
    if (fuzzy.score > 0) {
      return { score: fuzzy.score, fuzzyField: fuzzy.field };
    }
  }

  return { score };
}

/**
 * Determine match type based on score
 */
function determineMatchType(score: number): 'exact' | 'prefix' | 'contains' | 'fuzzy' {
  if (score >= MATCH_SCORE.EXACT_MIN) return 'exact';
  if (score >= MATCH_SCORE.PREFIX_MIN) return 'prefix';
  if (score >= MATCH_SCORE.CONTAINS_MIN) return 'contains';
  return 'fuzzy';
}

/**
 * Determine match field (best-effort for fuzzy-only matches).
 */
function determineMatchField(
  query: string,
  item: StockIndexItem,
  score: number,
  fuzzyField?: MatchField,
): MatchField {
  const q = query.toLowerCase();
  if (fuzzyField !== undefined && score > 0 && score < MATCH_SCORE.CONTAINS_MIN) {
    return fuzzyField;
  }

  const normalizedCanonicalCode = normalizeQuery(item.canonicalCode);
  const normalizedDisplayCode = normalizeQuery(item.displayCode);
  const normalizedName = normalizeQuery(item.nameZh);
  const normalizedPinyinFull = normalizeQuery(item.pinyinFull || '');
  const normalizedPinyinAbbr = normalizeQuery(item.pinyinAbbr || '');
  const normalizedAliases = item.aliases?.map(alias => normalizeQuery(alias)) || [];

  if (normalizedCanonicalCode.includes(q) ||
      normalizedDisplayCode.includes(q)) {
    return 'code';
  }
  if (normalizedName.includes(q)) return 'name';
  if (normalizedPinyinFull.includes(q) ||
      normalizedPinyinAbbr.includes(q)) {
    return 'pinyin';
  }
  if (normalizedAliases.some(a => a.includes(q))) return 'alias';
  return 'name';
}

/**
 * Escape HTML entities
 */
function escapeHtml(unsafe: string): string {
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Highlight matched text
 *
 * @param text - Original text
 * @param query - Query string
 * @returns Safe HTML string with highlight markers
 */
export function highlightMatch(text: string, query: string): string {
  const normalizedQuery = normalizeQuery(query);
  if (!normalizedQuery) return escapeHtml(text);

  const index = text.toLowerCase().indexOf(normalizedQuery);
  if (index === -1) return escapeHtml(text);

  const before = text.substring(0, index);
  const match = text.substring(index, index + normalizedQuery.length);
  const after = text.substring(index + normalizedQuery.length);

  // Return escaped segments joined by safe <mark> tags
  return `${escapeHtml(before)}<mark>${escapeHtml(match)}</mark>${escapeHtml(after)}`;
}
