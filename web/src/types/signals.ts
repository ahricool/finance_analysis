export type SignalMarket = 'CN' | 'US' | 'HK';

export type SignalDirection = 'bullish' | 'bearish' | 'sideways' | 'neutral';

export type SignalEvaluationPeriod = '30m' | '1h' | '1d' | '3d' | '7d';

export type SignalEvaluationStatus = 'not_applicable';

export type SignalEvaluationItem = {
  status?: SignalEvaluationStatus;
  reason?: string;
  price?: number;
  returnPct?: number;
  maxReturnPct?: number;
  minReturnPct?: number;
  evaluatedAt?: string;
};

export type SignalEvaluation = Partial<Record<SignalEvaluationPeriod, SignalEvaluationItem>>;

export type SignalItem = {
  id: number;
  market: SignalMarket;
  code: string;
  name?: string | null;
  signalType?: string | null;
  signalVersion: string;
  direction: SignalDirection;
  signalAt: string;
  signalPrice: number;
  evaluation: SignalEvaluation;
  createdAt: string;
  updatedAt: string;
};

export type SignalListResponse = {
  items: SignalItem[];
  total: number;
  page: number;
  pageSize: number;
};
