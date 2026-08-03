export function formatSecurityLabel(
  code: string | null | undefined,
  name: string | null | undefined,
  fallback = '—',
): string {
  const normalizedCode = String(code ?? '').trim();
  const normalizedName = String(name ?? '').trim();
  if (!normalizedCode) return normalizedName || fallback;
  if (!normalizedName || normalizedName.toUpperCase() === normalizedCode.toUpperCase()) {
    return normalizedCode;
  }
  return `${normalizedCode} - ${normalizedName}`;
}
