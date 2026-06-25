export type SupportedMarketType = 'CN' | 'US' | 'HK';

const MARKET_CURRENCY_CODE: Record<SupportedMarketType, string> = {
  CN: 'CNY',
  US: 'USD',
  HK: 'HKD',
};

const MARKET_CURRENCY_SYMBOL: Record<SupportedMarketType, string> = {
  CN: '¥',
  US: '$',
  HK: 'HK$',
};

function normalizeMarketType(marketType: string | null | undefined): SupportedMarketType {
  if (marketType === 'US' || marketType === 'HK') return marketType;
  return 'CN';
}

export function getMarketCurrencyCode(marketType: string | null | undefined): string {
  return MARKET_CURRENCY_CODE[normalizeMarketType(marketType)];
}

export function getMarketCurrencySymbol(marketType: string | null | undefined): string {
  return MARKET_CURRENCY_SYMBOL[normalizeMarketType(marketType)];
}

export function formatDecimalText(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const text = String(value).trim();
  if (!text) return '—';
  if (!text.includes('.')) return text;
  return text.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
}

export function parseDecimalInput(value: string): number | null {
  const text = value.trim();
  if (!/^\d+(?:\.\d+)?$/.test(text)) return null;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatMarketCurrencyAmount(
  value: string | number | null | undefined,
  marketType: string | null | undefined,
): string {
  if (value === null || value === undefined || value === '') return '—';
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '—';
  return `${getMarketCurrencySymbol(marketType)}${parsed.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatHoldingCostAmount(
  quantity: string | number | null | undefined,
  avgCost: string | number | null | undefined,
  marketType: string | null | undefined,
): string {
  if (avgCost === null || avgCost === undefined || avgCost === '') return '—';
  const parsedQuantity = Number(quantity);
  const parsedAvgCost = Number(avgCost);
  if (!Number.isFinite(parsedQuantity) || !Number.isFinite(parsedAvgCost)) return '—';
  return formatMarketCurrencyAmount(parsedQuantity * parsedAvgCost, marketType);
}
