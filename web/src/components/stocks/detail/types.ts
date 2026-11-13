import type { MarketType } from '@/api/watchList';
import type { FlowFilters } from '@/api/dragonTigerFlow';

export type StockDetailTab = 'overview' | 'industry' | 'holdings' | 'options' | 'trend' | 'etf' | 'confluence' | 'intraday' | 'dragon-tiger' | 'quant';

/** The originating observation stays attached when switching tabs. */
export interface StockDetailContext {
  tradeDate?: string;
  trendPeriod?: 10 | 20 | 40;
  view?: 'official' | 'preview';
  accountId?: number;
  positionId?: number;
  dragonTiger?: FlowFilters;
  dragonTigerConceptId?: string;
}

export interface StockDetailPanelProps {
  symbol: string;
  market: MarketType;
  context?: StockDetailContext;
}
