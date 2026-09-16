/**
 * Stock Index Type Definitions
 *
 * Stock data index for autocomplete functionality
 */

export type Market = 'CN' | 'HK' | 'US' | 'INDEX' | 'ETF' | 'BSE';
export type AssetType = 'stock' | 'index' | 'etf';

/**
 * Stock search suggestion item
 */
export interface StockSuggestion {
  /** Canonical code */
  canonicalCode: string;
  /** Display code */
  displayCode: string;
  /** Chinese name */
  nameZh: string;
  /** Market */
  market: Market;
  /** Asset type */
  assetType: AssetType;
  /** Match type */
  matchType: 'exact' | 'prefix' | 'contains' | 'fuzzy';
  /** Match field */
  matchField: 'code' | 'name';
  /** Sort score */
  score: number;
}
