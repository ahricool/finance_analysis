export type BacktestEngineKey = 'backtrader' | 'rqalpha';
export type BacktestMarket = 'US' | 'CN' | 'HK';
export type BacktestStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';

export type BacktestEngine = {
  key: BacktestEngineKey;
  name: string;
  description: string;
  displayOrder: number;
  isDefault: boolean;
  recommended: boolean;
  available: boolean;
  unavailableReason: string | null;
  version: string | null;
  supportedMarkets: BacktestMarket[];
  supportedStrategies: string[];
};

export type StrategyParameter = {
  key: string;
  name: string;
  type: 'integer';
  default: number;
  minimum: number;
  maximum: number;
};

export type BacktestStrategy = {
  key: string;
  name: string;
  description: string;
  version: string;
  frequency: string;
  supportedMarkets: BacktestMarket[];
  supportedEngines: BacktestEngineKey[];
  parameters: StrategyParameter[];
};

export type BacktestSymbol = {
  id: number;
  market: BacktestMarket;
  code: string;
  name: string;
  lotSize: number | null;
};

export type BacktestConfig = {
  engine: BacktestEngineKey;
  strategyKey: string;
  market: BacktestMarket;
  code: string;
  startDate: string;
  endDate: string;
  initialCash: number;
  benchmarkCode: string | null;
  parameters: Record<string, number>;
};

export type BacktestPreflight = {
  ready: boolean;
  engine: BacktestEngineKey;
  engineVersion: string | null;
  strategyKey: string;
  market: BacktestMarket;
  code: string;
  availableDateFrom: string | null;
  availableDateTo: string | null;
  requestedTradingDays: number;
  availableTradingDays: number;
  coverageRatio: number;
  warmupDays: number;
  warnings: string[];
  errors: string[];
};

export type BacktestSummary = {
  initialCash?: number;
  finalEquity?: number;
  totalReturnPct?: number;
  annualizedReturnPct?: number;
  benchmarkReturnPct?: number;
  excessReturnPct?: number;
  maxDrawdownPct?: number;
  sharpeRatio?: number | null;
  volatilityPct?: number;
  tradeCount?: number;
  winRatePct?: number;
};

export type BacktestRun = {
  id: number;
  uid: number;
  taskId: string | null;
  engine: BacktestEngineKey;
  engineVersion: string | null;
  engineConfig: Record<string, unknown>;
  strategyKey: string;
  strategyName: string;
  strategyVersion: string;
  market: BacktestMarket;
  symbolId: number;
  code: string;
  startDate: string;
  endDate: string;
  initialCash: number;
  benchmarkCode: string | null;
  parameters: Record<string, number>;
  priceMode: string;
  marketRuleVersion: string;
  status: BacktestStatus;
  progress: number;
  summary: BacktestSummary;
  warnings: string[];
  error: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
};

export type BacktestTrade = {
  id: number;
  runId: number;
  code: string;
  engineOrderId: string | null;
  side: 'buy' | 'sell';
  signalDate: string;
  orderDate: string;
  tradeDate: string;
  quantity: number;
  price: number;
  grossAmount: number;
  commission: number;
  tax: number;
  otherFee: number;
  totalFee: number;
  cashAfter: number;
  positionAfter: number;
  returnPct: number | null;
  pnl: number | null;
  exitReason: string | null;
};

export type BacktestEquity = {
  tradingDate: string;
  cash: number;
  positionValue: number;
  totalEquity: number;
  benchmarkEquity: number | null;
  dailyReturnPct: number;
  cumulativeReturnPct: number;
  benchmarkReturnPct: number | null;
  drawdownPct: number;
};

export type BacktestRunList = { items: BacktestRun[]; total: number; page: number; pageSize: number };
