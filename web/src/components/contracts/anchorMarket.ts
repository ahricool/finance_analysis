export function anchorMarket(code: string) {
  if (code.endsWith('.US')) return 'US';
  if (code.endsWith('.HK')) return 'HK';
  if (/\.(SH|SZ|BJ)$/.test(code)) return 'CN';
  return code.endsWith('.CRYPTO') ? 'CRYPTO' : 'OTHER';
}
