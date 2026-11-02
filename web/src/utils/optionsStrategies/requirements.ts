/** Structural prerequisites only; no account eligibility or monetary cost estimate. */
export const STRATEGY_REQUIREMENTS = {
  buy: { sellsOptions: false, stock: 'none', cashReserve: false, labels: ['支付权利金'] },
  sell: { sellsOptions: true, stock: 'none', cashReserve: false, labels: ['含卖出腿'] },
  longStock: { sellsOptions: false, stock: 'long', cashReserve: false, labels: ['需持有正股'] },
  shortStock: { sellsOptions: false, stock: 'short', cashReserve: false, labels: ['需融券做空'] },
  longStockSell: { sellsOptions: true, stock: 'long', cashReserve: false, labels: ['含卖出腿', '需持有正股'] },
  shortStockSell: { sellsOptions: true, stock: 'short', cashReserve: false, labels: ['含卖出腿', '需融券做空'] },
  cashBuy: { sellsOptions: false, stock: 'none', cashReserve: true, labels: ['需预留行权本金'] },
  cashSell: { sellsOptions: true, stock: 'none', cashReserve: true, labels: ['含卖出腿', '需预留接股本金'] },
  wheel: { sellsOptions: true, stock: 'long', cashReserve: true, labels: ['含卖出腿', '预留本金／接股持股'] },
} as const;
export type StrategySetup = keyof typeof STRATEGY_REQUIREMENTS;
export type StrategyGroup = 'buyer' | 'seller' | 'capital';
export const STRATEGY_GROUPS = [
  { id: 'buyer', label: '纯买方', english: 'Buy only', description: '仅买期权 · 无正股前提' },
  { id: 'seller', label: '含卖出腿', english: 'Option selling', description: '含卖出期权 · 核验保证金' },
  { id: 'capital', label: '正股／资金占用', english: 'Stock & capital', description: '持股、融券或预留本金' },
] as const;
export function strategyGroup(setup: StrategySetup): StrategyGroup {
  const requirements = STRATEGY_REQUIREMENTS[setup];
  if (requirements.stock !== 'none' || requirements.cashReserve) return 'capital';
  return requirements.sellsOptions ? 'seller' : 'buyer';
}
